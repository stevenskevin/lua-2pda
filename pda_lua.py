# Copyright (c) 2020 Kevin Stevens
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import string

import pda


def bstr_to_set(b):
    """
    Convert a byte string to a set of the length-1 bytes obejcts within it.
    """
    return set(bytes([c]) for c in b)


def u8_complement(s):
    """
    Return the set of all length-1 bytes objects not in s (which is of
    type bytes, or set of length-1 bytes objects).
    """
    return without(ALL, s)


def without(s, removals):
    """
    Return the set of all length-1 bytes objects in s and not in removals
    (both of which are either of type bytes, or set of length-1 bytes objects).
    """
    if isinstance(s, bytes):
        s = bstr_to_set(s)
    elif isinstance(s, set):
        s = set(s)
    else:
        raise TypeError(s)

    if isinstance(removals, bytes):
        removals = bstr_to_set(removals)
    elif not isinstance(removals, set):
        raise TypeError(removals)

    for r in removals:
        s.remove(r)
    return s

# See lctype.h
ALL = bstr_to_set(bytes(range(0x100)))
IN_LISLALPHA = bstr_to_set(string.ascii_letters.encode('cp1252') + b'_')
NOT_LISLALPHA = u8_complement(IN_LISLALPHA)
IN_LISLALNUM = bstr_to_set(string.ascii_letters.encode('cp1252') + string.digits.encode('cp1252') + b'_')
NOT_LISLALNUM = u8_complement(IN_LISLALNUM)
IN_LISDIGIT = bstr_to_set(string.digits.encode('cp1252'))
NOT_LISDIGIT = u8_complement(IN_LISDIGIT)
IN_LISSPACE = bstr_to_set(string.whitespace.encode('cp1252'))
NOT_LISSPACE = u8_complement(IN_LISSPACE)
IN_LISPRINT = bstr_to_set(string.printable.encode('cp1252'))
NOT_LISPRINT = u8_complement(IN_LISPRINT)
IN_LISXDIGIT = bstr_to_set(string.hexdigits.encode('cp1252'))
NOT_LISXDIGIT = u8_complement(IN_LISXDIGIT)

# (Note: the Lua parser uses hardcoded Arabic numeral characters, like this)
DIGITS = bstr_to_set(b'0123456789')
ONLY_HEX_DIGITS = bstr_to_set(b'abcdefABCDEF')
HEX_DIGITS = DIGITS | ONLY_HEX_DIGITS


def _make_transitions():
    """
    Create the transitions table for the Lua 2PDA
    """
    transitions = {}
    FAIL_TRANSITION = ('FAIL', 'stay', 'read', None)

    KEYWORDS = [
        'and', 'break', 'do', 'else', 'elseif', 'end',
        'false', 'for', 'function', 'goto', 'if', 'in',
        'local', 'nil', 'not', 'or', 'repeat', 'return',
        'then', 'true', 'until', 'while']

    CHECK_IF_ONLY_NAME_STACK_SYMBOLS = ['beginning',
                                        'only_name',
                                        'not_only_name']


    ####################################################################
    ####################################################################
    ################## Subsystem enter/exit functions ##################
    ####################################################################
    ####################################################################

    # (These have to be defined first instead of with each subsystem
    # because a few of the subsystems are mutually recursive, and thus
    # need to be able to call each other's entrance functions)


    def read_whitespace(start_state, minus_transition, *, required_stack_value=None):
        """
        Read whitespace, including any comments. Remains on the current
        state, except while reading comments.

        Note that, when using this function on a state, you CANNOT also
        add your own transition on "-" away from that state! Use
        minus_transition instead.

        - start_state: the state we start at
        - minus_transition: transition to use upon reading a minus and
          then landing on something that's not a minus. At this point,
          minus has already been consumed, and we can't go back and
          un-consume it.
        - required_stack_value: this must be initially on top of the
          stack for whitespace/comments to be recognized

        When minus_transition is taken, the stack will be the same as
        when whitespace reading began.
        """
        this_stack_value = 'comment__' + start_state

        # Skip any whitespace while on the start state
        for c in IN_LISSPACE:
            transitions[(start_state, c, required_stack_value)] = (start_state, 'right', 'read', None)

        # Comment?
        transitions[(start_state, b'-', required_stack_value)] = ('possible_comment_-', 'right', 'push', this_stack_value)

        # If we're in "possible_comment_-", and read anything other than "-", transition to minus_transition
        # (after popping this_stack_value off the stack)
        for c in u8_complement(b'-'):
            intermediate_state = 'possible_comment_-__' + start_state
            transitions[('possible_comment_-', c, this_stack_value)] = (intermediate_state, 'stay', 'pop', None)
            transitions[(intermediate_state, c, None)] = minus_transition
        # If there is another "-", we'll pick it up in the general comment parser.

        # End of a single-line comment -- return to original state
        transitions[('comment_single_line', b'\r', this_stack_value)] = (start_state, 'right', 'pop', None)
        transitions[('comment_single_line', b'\n', this_stack_value)] = (start_state, 'right', 'pop', None)

        # End of a multi-line comment -- return to original state
        transitions[('comment_multiline_end', b']', this_stack_value)] = (start_state, 'right', 'pop', None)


    def read_name_or_keyword(start_state, name_transition, keyword_transition, *, required_stack_value=None):
        """
        Read a "Name" from the Lua grammar, which is defined as follows:

            (https://www.lua.org/manual/5.3/manual.html#3.1)
            Names (also called identifiers) in Lua can be any string of
            letters, digits, and underscores, not beginning with a digit
            and not being a reserved word. Identifiers are used to name
            variables, table fields, and labels.

        If the name turns out to be a keyword, then it's not really a
        name. But having a function that can check for both is useful.

        - start_state: the state we start at
        - name_transition: transition to use upon successfully reading a
          name (defined as reading a non-alphanumeric character after
          reading a full name which is not a keyword)
        - keyword_transition: transition to use upon successfully
          reading a keyword (defined as reading a non-alphanumeric
          character after reading a full keyword)
        - required_stack_value: this must be initially on top of the
          stack for the name or keyword to be recognized

        Note that, just before the keyword transition, the keyword
        itself will be on the top of the stack. But just before the name
        transition, there will be nothing extra on top of the stack.
        """
        this_stack_value = 'name_or_keyword__' + start_state

        # Enter subsystem
        # Precondition: in start_state, with nothing on top of stack
        # Postcondition: in "name_or_keyword" state, with this_stack_value on top of stack
        for c in IN_LISLALPHA:
            transitions[(start_state, c, required_stack_value)] = ('name_or_keyword', 'stay', 'push', this_stack_value)

        # Exit subsystem (name)
        # Precondition: in "name" state, with this_stack_value on top of stack
        # Postcondition: taking name_transition, with nothing on top of stack
        for c in NOT_LISLALNUM:
            intermediate_state = 'name_from__' + start_state
            transitions[('name', c, this_stack_value)] = (intermediate_state, 'stay', 'pop', None)
            transitions[(intermediate_state, c, None)] = name_transition

        # Exit subsystem (keyword)
        # Precondition: in any of the "keyword_[keyword]" states, with this_stack_value on top of stack
        # Postcondition: taking keyword_transition, with keyword on top of stack
        for keyword in KEYWORDS:
            intermediate_state = 'keyword_' + keyword + '_from__' + start_state
            for c in NOT_LISLALNUM:
                transitions[('keyword_' + keyword, c, this_stack_value)] = (intermediate_state, 'stay', 'replace', keyword)
                transitions[(intermediate_state, c, None)] = keyword_transition


    def read_name_list(start_state, name_transition, keyword_transition, *, required_stack_value=None):
        """
        Read a name list.

        - start_state: the state we start at
        - name_transition: transition to use upon successfully reading
          one or more names (defined as reading a non-alphanumeric
          character other than "," after reading a full name which is
          not a keyword)
        - keyword_transition: transition to use upon successfully
          reading a keyword (defined as reading a non-alphanumeric
          character after reading a full keyword, which is the first
          thing in the name list)
        - required_stack_value: this must be initially on top of the
          stack for the name or keyword to be recognized

        Unlike read_name_or_keyword(), this function consumes trailing
        whitespace after reading names. It has to, since you could have
        a situation like
            return a          ,b          ;end
        and so it has to read all the whitespace following each name
        to determine if the name list continues or not.

        It does NOT consume leading whitespace.

        Note: right now, you can't have a name list that's closed by a
        minus sign, because comments complicates this and I don't think
        it would ever be used anywhere. Implement that only if needed.

        See docstring for read_name_or_keyword() for more details.
        """
        this_stack_value = 'name_list__' + start_state

        # Enter subsystem
        # Precondition: in start_state, with nothing on top of stack
        # Postcondition: in "name" state, with this_stack_value on top of stack
        for c in ALL:
            transitions[(start_state, c, required_stack_value)] = ('name_list_start', 'stay', 'push', this_stack_value)

        # Exit subsystem (usual route)
        # Precondition: in "name_list_exit_name" state, with this_stack_value on top of stack
        # Postcondition: taking name_transition, with nothing on top of stack
        for c in ALL:
            intermediate_state = 'name_list_exit_name_from__' + start_state
            transitions[('name_list_exit_name', c, this_stack_value)] = (intermediate_state, 'stay', 'pop', None)
            transitions[(intermediate_state, c, None)] = name_transition

        # Exit subsystem (keyword encountered)
        # Precondition: in "name_list_exit_keyword" state, with keyword name above this_stack_value on top of stack
        # Postcondition: taking keyword_transition, with the keyword on top of stack
        for c in ALL:
            for k in KEYWORDS:
                intermediate_state_1 = f'name_list_exit_keyword__{k}'
                intermediate_state_2 = f'name_list_exit_keyword__{k}__from__{start_state}'
                intermediate_state_3 = f'name_list_exit_keyword_from__{start_state}'
                # Pop the keyword off the stack, and put it in the state name instead
                transitions[('name_list_exit_keyword', c, k)] = (intermediate_state_1, 'stay', 'pop', None)
                # Pop the "this_stack_value" off the stack, and put it in the state name instead
                transitions[(intermediate_state_1, c, this_stack_value)] = (intermediate_state_2, 'stay', 'pop', None)
                # Push the keyword back onto the stack
                transitions[(intermediate_state_2, c, None)] = (intermediate_state_3, 'stay', 'push', k)
                # Take the actual final transition
                transitions[(intermediate_state_3, c, None)] = keyword_transition


    def read_lvalue_or_rvalue(start_state, already_read_name, transition, minus_transition, period_transition, colon_transition,
            keyword_transition=FAIL_TRANSITION,
            *, check_if_only_name=False, check_if_function_call=False):
        """
        Read an L-value or R-value (corresponding to the "var" and
        "prefixexp" Lua grammar rules). See "lvalue-rvalue-notes.txt".

        This function leaves a stack symbol on top of the stack --
        either "rvalue" or "lvalue_or_rvalue" -- which you can use to
        deduce if what was read could be valid as an lvalue or would
        only be valid as an rvalue.

        - start_state: the state we start at
        - already_read_name: True if a name has already been read, False
          otherwise
        - transition: transition to use upon encountering something that
          implies the end of the thing
        - minus_transition: transition to use upon reading a minus and
          then landing on something that's not a minus. At this point,
          minus has already been consumed, and we can't go back and
          un-consume it. This is otherwise equivalent to the main exit
          transition.
          Note that trailing whitespace is NOT consumed in this case!
        - period_transition: transition to use upon reading a period and
          then landing on another period. At this point, period has
          already been consumed, and we can't go back and un-consume it.
          This is otherwise equivalent to the main exit transition.
          Note that trailing whitespace is NOT consumed in this case!
        - colon_transition: transition to use upon reading a colon and
          then landing on something that's not a name. At this point,
          colon has already been consumed, and we can't go back and
          un-consume it. This is otherwise equivalent to the main exit
          transition.
          Note that trailing whitespace is NOT consumed in this case!
        - keyword_transition: transition to use if the first thing that
          is read is a keyword.
          Note that trailing whitespace is NOT consumed in this case!
          Also note that NO new symbols are left on the stack in this
          case, except for the keyword itself.
        - check_if_only_name: causes this function to leave an extra
          element on the stack (only if exiting via "transition" or
          "minus_transition"), which will be 'only_name' if the only
          thing that was read was a single name, or 'not_only_name' if
          the lvalue/rvalue was anything more. See below for where
          exactly this will be placed on the stack.
        - check_if_function_call: causes this function to leave an extra
          element on the stack (only if exiting via "transition" or
          "minus_transition"), which will be 'only_name' if the only
          thing that was read was a single name, or 'not_only_name' if
          the lvalue/rvalue was anything more. See below for where
          exactly this will be placed on the stack.

        The order in which stack symbols will be left on the stack
        (top to bottom):
        - "lvalue_or_rvalue" or "rvalue"
        - "only_name" or "not_only_name"         (optional -- only if
                                                 check_if_only_name is True)
        - "function_call" or "not_function_call" (optional -- only if
                                                 check_if_function_call is True)

        This function handles trailing whitespace automatically, except
        for exit transitions that specify otherwise. It does NOT handle
        leading whitespace.
        """
        this_stack_value = 'lrvalue__' + start_state
        entry_point = '2' if already_read_name else '1'

        # Enter subsystem
        # Precondition: in start_state, with nothing on top of stack
        # Postcondition: in "lrvalue_start_1" or "lrvalue_start_2"
        #     state (depending on already_read_name), with
        #     this_stack_value on top of stack
        for c in ALL:
            transitions[(start_state, c, None)] = ('lrvalue_start_' + entry_point, 'stay', 'push', this_stack_value)

        # Exit subsystem
        # AND
        # Exit subsystem (minus read)
        # AND
        # Exit subsystem (period read)

        # Precondition: in "lrvalue[_-|_.]_exit" state, with
        #     the current state (as set by
        #     _lrvalue_set_stack_state_and_read_next_part()) on top of
        #     stack, followed by this_stack_value
        # Postcondition: taking [minus_]transition, with the top of the
        #     stack looking like this (top to bottom):
        #     - "lvalue_or_rvalue" or "rvalue"
        #     - "only_name" or "not_only_name"         (optional -- only if check_if_only_name is True)
        #     - "function_call" or "not_function_call" (optional -- only if check_if_function_call is True)
        for mod, this_transition in [('', transition), ('_-', minus_transition), ('_.', period_transition), ('_:', colon_transition)]:
            for exit_option_1 in ['lvalue_or_rvalue', 'rvalue']:
                for exit_option_2 in ['only_name', 'not_only_name']:
                    for exit_option_3 in ['function_call', 'not_function_call']:
                        state_stack_value = exit_option_1 + '__' + exit_option_2 + '__' + exit_option_3
                        intermediate_state_1 = f'lrvalue_exit{mod}_with__' + state_stack_value
                        extra_intermediate_state = f'lrvalue_exit{mod}_from__' + this_stack_value + '__with__' + state_stack_value

                        to_push = []
                        if check_if_function_call:
                            to_push.append(exit_option_3)
                        if check_if_only_name:
                            to_push.append(exit_option_2)
                        to_push.append(exit_option_1)

                        for c in ALL:
                            # pop state_stack_value
                            transitions[(f'lrvalue{mod}_exit', c, state_stack_value)] = (intermediate_state_1, 'stay', 'pop', None)

                            current_intermediate_state = intermediate_state_1
                            next_intermediate_state_num = 1
                            action = 'replace' # replace the first time; push subsequent times
                            stack_value_to_check_against = this_stack_value # this_stack_value the first time; None subsequent times

                            for tp in to_push:
                                next_intermediate_state = extra_intermediate_state + '__' + str(next_intermediate_state_num)
                                transitions[(current_intermediate_state, c, stack_value_to_check_against)] = \
                                    (next_intermediate_state, 'stay', action, tp)

                                # prepare for next iteration
                                action = 'push'
                                stack_value_to_check_against = None
                                current_intermediate_state = next_intermediate_state
                                next_intermediate_state_num += 1

                            transitions[(current_intermediate_state, c, None)] = this_transition

        # Exit subsystem (keyword)
        # Precondition: in "lrvalue_exit_keyword" state, with the
        #     keyword on top of stack, followed by this_stack_value
        # Postcondition: taking keyword_transition, with keyword on top
        #     of stack
        for keyword in KEYWORDS:
            intermediate_state_1 = f'lrvalue_exit_keyword_with__' + keyword
            intermediate_state_2 = f'lrvalue_exit_keyword_from__' + start_state + '__with__' + keyword
            for c in ALL:
                transitions[('lrvalue_exit', c, keyword)] = (intermediate_state_1, 'stay', 'pop', None)
                transitions[(intermediate_state_1, c, this_stack_value)] = (intermediate_state_2, 'stay', 'replace', keyword)
                transitions[(intermediate_state_2, c, None)] = keyword_transition


    def _lrvalue_init_stack_state_and_read_next_part(start_state, characters_to_transition_on, right_or_stay,
            lvalue_or_rvalue_vs_rvalue, only_name_vs_not_only_name, function_call_vs_not_function_call):
        """
        Helper function for the LRvalue subsystem to initialize the
        stack state to represent certain values, and then transition to
        lrvalue_read_next_part
        """
        stack_value = lvalue_or_rvalue_vs_rvalue + '__' + only_name_vs_not_only_name + '__' + function_call_vs_not_function_call
        if isinstance(characters_to_transition_on, bytes):
            characters_to_transition_on = bstr_to_set(characters_to_transition_on)
        for c in characters_to_transition_on:
            transitions[(start_state, c, None)] = ('lrvalue_read_next_part', right_or_stay, 'push', stack_value)


    def _lrvalue_set_stack_state_and_read_next_part(start_state, characters_to_transition_on, right_or_stay,
            lvalue_or_rvalue_vs_rvalue, only_name_vs_not_only_name, function_call_vs_not_function_call,
            *, is_colon_version=False):
        """
        Helper function for the LRvalue subsystem to change the stack
        state to represent certain values, and then transition to
        lrvalue_read_next_part
        """
        target_state = 'lrvalue_read_next_part' + ('_:' if is_colon_version else '')
        stack_value = lvalue_or_rvalue_vs_rvalue + '__' + only_name_vs_not_only_name + '__' + function_call_vs_not_function_call
        if isinstance(characters_to_transition_on, bytes):
            characters_to_transition_on = bstr_to_set(characters_to_transition_on)
        for c in characters_to_transition_on:
            transitions[(start_state, c, None)] = (target_state, right_or_stay, 'replace', stack_value)


    def read_expression(start_state, transition,
            end_transition=FAIL_TRANSITION, elseif_transition=FAIL_TRANSITION,
            else_transition=FAIL_TRANSITION, until_transition=FAIL_TRANSITION,
            semicolon_transition=FAIL_TRANSITION, rparen_transition=FAIL_TRANSITION,
            equals_transition=FAIL_TRANSITION,
            trailing_name_transition=FAIL_TRANSITION,
            colon_transition=FAIL_TRANSITION,
            *, required_stack_value=None, check_if_only_name=False):
        """
        Read an expression.

        - start_state: the state we start at
        - transition: transition to use upon encountering something that
          would seem to imply the end of the expression
        - end_transition / elseif_transition / else_transition /
          until_transition: transition to use if the expression is just
          the specified keyword (used by return statements) Note that
          trailing whitespace is NOT consumed in this case!
          (But the keyword itself is.)
          Requested output variables are NOT left on the stack.
        - semicolon_transition: transition to use if ';' is the first
          thing encountered (used by return statements)
          Note that trailing whitespace is NOT consumed in this case!
          (But the ';' is.)
          Requested output variables are NOT left on the stack.
        - rparen_transition: transition to use if ')' is the first
          thing encountered (used by function calls)
          Note that trailing whitespace is NOT consumed in this case!
          (But the ')' is.)
          Requested output variables are NOT left on the stack.
        - equals_transition: transition to use if read_expression()
          consumed an '=' in the hopes of it being the '==' binary
          operator, but it turned out not to be.
          Note that trailing whitespace is NOT consumed in this case!
          Requested output variables ARE left on the stack.
        - trailing_name_transition: transition to use if
          read_expression() consumed a name in the hopes of it being
          'and' or 'or', but it turned out not to be.
          Note that trailing whitespace is NOT consumed in this case!
          Requested output variables ARE left on the stack.
        - colon_transition: transition to use if read_expression()
          consumed a ':'' in the hopes of it being a ':'-style function
          call, but it turned out not to be.
          Note that trailing whitespace is NOT consumed in this case!
          (But the ':' is.)
          Requested output variables ARE left on the stack.
        - required_stack_value: this must be initially on top of the
          stack for the expression to be recognized
        - check_if_only_name: causes this function to leave an extra
          element on top of the stack (only if exiting via the primary
          transition), which will be 'only_name' if the only thing that
          was read was a single name, or 'not_only_name' if the
          expression was anything else. (Accidentally reading an extra
          '=' in the equals_transition does not count as "anything
          else.")

        DO NOT CALL read_whitespace() ON THE SAME STATE THAT YOU CALL
        THIS FUNCTION ON!!! They conflict because they both check for
        "-". This function handles leading and trailing whitespace
        automatically (unless "end" or ";" or "=" is read, so you can
        fail quickly)
        """
        this_stack_value = 'expression__' + start_state

        # Enter subsystem
        # Precondition: in start_state, with nothing on top of stack
        # Postcondition: in "expression" state, with 'beginning' (from
        #     CHECK_IF_ONLY_NAME_STACK_SYMBOLS) on top of stack, and
        #     this_stack_value just below it
        for c in ALL:
            transitions[(start_state, c, required_stack_value)] = ('expression_start', 'stay', 'push', this_stack_value)
            transitions[('expression_start', c, None)] = ('expression', 'stay', 'push', 'beginning')
        read_whitespace('expression_start',
            ('expression_start', 'stay', 'read', None))
        # ^ "exp ::= - exp" is a valid grammar production, so if
        # read_whitespace() consumes a '-', that's not a problem. We
        # just have to go back to expression_start to read any further
        # whitespace following the '-'.

        # Exit subsystem (regularly, or "=" or name or ":" encountered)
        # Precondition: in "expression_exit" state, with the current
        #     check_if_only_name state on top of stack, and
        #     this_stack_value just below it
        # Postcondition: taking transition, with either nothing or the
        #     check_if_only_name state (depending on check_if_only_name)
        #     on top of stack
        for type, this_transition in [('', transition),
                                      ('_=', equals_transition),
                                      ('_trailing_name', trailing_name_transition),
                                      ('_:', colon_transition)]:
            for c in ALL:
                for symb in CHECK_IF_ONLY_NAME_STACK_SYMBOLS:
                    # Pop stack symbol and put it in the state name
                    intermediate_state_1 = f'expression_exit{type}_with__' + symb
                    transitions[(f'expression_exit{type}', c, symb)] = (intermediate_state_1, 'stay', 'pop', None)

                    # Pop this_stack_value and either replace it with the
                    # stack symbol, or don't
                    intermediate_state_2 = f'expression_exit{type}_from__' + start_state
                    if check_if_only_name:
                        transitions[(intermediate_state_1, c, this_stack_value)] = (intermediate_state_2, 'stay', 'replace', symb)
                    else:
                        transitions[(intermediate_state_1, c, this_stack_value)] = (intermediate_state_2, 'stay', 'pop', None)
                
                # Transition out using the transition provided to us
                transitions[(intermediate_state_2, c, None)] = this_transition

        # Exit subsystem ("end" / "elseif" / "else" / "until" / ";" / ")" encountered)
        # Precondition: in "expression_exit_end" or "expression_exit_;"
        #     or "expression_exit_)" state, with the current
        #     check_if_only_name state on top of stack, and
        #     this_stack_value just below it
        # Postcondition: taking appropriate transition, with nothing on
        #     top of stack
        for k, special_transition in [('end', end_transition),
                                      ('elseif', elseif_transition),
                                      ('else', else_transition),
                                      ('until', until_transition),
                                      (';', semicolon_transition),
                                      (')', rparen_transition)]:
            intermediate_state = 'expression_exit_' + k + '_from__' + start_state
            for c in ALL:
                transitions[(f'expression_exit_{k}', c, None)] = (f'expression_exit_{k}_1', 'stay', 'pop', None)
                transitions[(f'expression_exit_{k}_1', c, this_stack_value)] = (intermediate_state, 'stay', 'pop', None)
                transitions[(intermediate_state, c, None)] = special_transition


    def read_expression_list(start_state, transition,
            end_transition=FAIL_TRANSITION, elseif_transition=FAIL_TRANSITION,
            else_transition=FAIL_TRANSITION, until_transition=FAIL_TRANSITION,
            semicolon_transition=FAIL_TRANSITION, rparen_transition=FAIL_TRANSITION,
            trailing_name_transition=FAIL_TRANSITION,
            colon_transition=FAIL_TRANSITION,
            *, required_stack_value=None):
        """
        Read an expression list.

        - start_state: the state we start at
        - transition: transition to use upon encountering something that
          would seem to imply the end of the expression list
        - end_transition / elseif_transition / else_transition /
          until_transition / semicolon_transition / rparen_transition /
          trailing_name_transition / colon_transition: transition to use
          if the last call to read_expression() exited via its
          transition of the same name. For details, please see the
          docstring for read_expression().
        - required_stack_value: this must be initially on top of the
          stack for the expression to be recognized

        DO NOT CALL read_whitespace() ON THE SAME STATE THAT YOU CALL
        THIS FUNCTION ON!!! They conflict because they both check for
        "-". This function handles leading and trailing whitespace
        automatically (unless "end" or ";" is read, so you can fail
        quickly)
        """
        this_stack_value = 'expression_list__' + start_state

        # Enter subsystem
        # Precondition: in start_state, with nothing on top of stack
        # Postcondition: in "expression_list_start" state, with this_stack_value on top of stack
        for c in ALL:
            transitions[(start_state, c, required_stack_value)] = ('expression_list_start', 'stay', 'push', this_stack_value)

        # Exit subsystem
        # Precondition: in "expression_list_exit" state, with this_stack_value on top of stack
        # Postcondition: taking transition, with nothing on top of stack
        for c in ALL:
            intermediate_state = 'expression_list_exit_from__' + start_state
            transitions[('expression_list_exit', c, this_stack_value)] = (intermediate_state, 'stay', 'pop', None)
            transitions[(intermediate_state, c, None)] = transition

        # Exit subsystem ("end" / "elseif" / "else" / "until" / ";" / ")" / trailing-name encountered)
        # Precondition: in "expression_list_exit_{keyword}" state, with this_stack_value on top of stack
        # Postcondition: taking {keyword}_transition, with nothing on top of stack
        for k, trans in [('end', end_transition),
                         ('elseif', elseif_transition),
                         ('else', else_transition),
                         ('until', until_transition),
                         (';', semicolon_transition),
                         (')', rparen_transition),
                         ('trailing_name', trailing_name_transition),
                         (':', colon_transition)]:
            for c in ALL:
                intermediate_state = f'expression_list_exit_{k}_from__' + start_state
                transitions[('expression_list_exit_' + k, c, this_stack_value)] = (intermediate_state, 'stay', 'pop', None)
                transitions[(intermediate_state, c, None)] = trans


    ####################################################################
    ####################################################################
    ################# Long strings / multiline comments ################
    ####################################################################
    ####################################################################
    # These are similar enough to be worth parsing in the same way.

    # Note: I don't believe it's possible in general to count "="s and
    # compare them again in a PDA. So we hardcode it up to 10 ='s, and
    # treat anything more than 10 as if it was 10.
    EQUALS_TO_SUPPORT = 10 # supports 0 ='s through this number (inclusive)

    # To enter this subsystem:
    # - push something you can use to later return on the stack
    # - transition to state "multiline_comment_or_long_string_start"
    #   BEFORE consuming the leading "["
    #   --OR--
    #   transition to state "multiline_comment_or_long_string_start_2"
    #   AFTER consuming the leading "["
    # To exit:
    # - make a transition from "multiline_comment_or_long_string_end" back
    #   to your own state, which consumes a ']', and checks for your
    #   stack value and pops it

    # Note:
    # Make sure to treat a failed closing "]" as the possible start of
    # the real ending; that is, account for "code() --[===[ comment ]=]===] code()"

    MCOLS = 'multiline_comment_or_long_string'  # So I don't have to keep typing it


    # Read initial '[', and push a '' onto the stack (representing
    # the number of ='s read so far)
    for c in ALL:
        transitions[(f'{MCOLS}_start', c, None)] = (f'{MCOLS}_end_opening_fail', 'stay', 'read', None)
    transitions[(f'{MCOLS}_start', b'[', None)] = (f'{MCOLS}_start_[', 'right', 'push', '')

    # ALTERNATIVE ENTRY POINT
    # Already past the initial '[', so now we should be on either a '['
    # or a '='. Push a '' onto the stack (representing the number of ='s
    # read so far)
    for c in ALL:
        transitions[(f'{MCOLS}_start_2', c, None)] = (f'{MCOLS}_end_opening_fail', 'stay', 'read', None)
    transitions[(f'{MCOLS}_start_2', b'[', None)] = (f'{MCOLS}_start_[', 'stay', 'push', '')
    transitions[(f'{MCOLS}_start_2', b'=', None)] = (f'{MCOLS}_start_[', 'stay', 'push', '')

    # Read 1-N equals
    for c in u8_complement(b'='):
        transitions[(f'{MCOLS}_start_[', c, None)] = (f'{MCOLS}_end_opening_fail', 'stay', 'pop', None)
    for i in range(1, EQUALS_TO_SUPPORT + 1):
        transitions[(f'{MCOLS}_start_[', b'=', '=' * (i - 1))] = (f'{MCOLS}_start_[', 'right', 'replace', '=' * i)

    # More than N equals are treated as if there were only N
    transitions[(f'{MCOLS}_start_[', b'=', None)] = (f'{MCOLS}_start_[', 'right', 'read', None)

    # Second opening '['
    transitions[(f'{MCOLS}_start_[', b'[', None)] = (MCOLS, 'right', 'read', None)

    # At this point we're in the MCOLS state, with the number of ='s we read
    # on the stack (as one stack symbol).

    # Skip over stuff
    for c in ALL:
        transitions[(MCOLS, c, None)] = (MCOLS, 'right', 'read', None)

    # Detect start of possible ending
    transitions[(MCOLS, b']', None)] = (f'{MCOLS}_possible_end', 'right', 'push', '')

    # Detect failed possible endings via invalid characters
    for c in u8_complement(b'=]'):
        transitions[(f'{MCOLS}_possible_end', c, None)] = (MCOLS, 'right', 'pop', None)
    # Count equals
    for i in range(1, EQUALS_TO_SUPPORT + 1):
        transitions[(f'{MCOLS}_possible_end', b'=', '=' * (i - 1))] = (f'{MCOLS}_possible_end', 'right', 'replace', '=' * i)
    transitions[(f'{MCOLS}_possible_end', b'=', None)] = (f'{MCOLS}_possible_end', 'right', 'read', None)
    # Upon reaching ']', check if the top two stack values are equal
    transitions[(f'{MCOLS}_possible_end', b']', None)] = (f'{MCOLS}_possible_end_2', 'stay', 'read', None)
    for i in range(EQUALS_TO_SUPPORT + 1):
        transitions[(f'{MCOLS}_possible_end_2', b']', '=' * i)] = (f'{MCOLS}_possible_end_' + ('=' * i), 'stay', 'pop', None)
        transitions[(f'{MCOLS}_possible_end_' + ('=' * i), b']', '=' * i)] = (f'{MCOLS}_end', 'stay', 'pop', None)
        # If they're *not* equal, go back to _possible_end because we did just read
        # another ']' that could be the start of the true ending
        transitions[(f'{MCOLS}_possible_end_' + ('=' * i), b']', None)] = (f'{MCOLS}_possible_end', 'right', 'push', '')


    ####################################################################
    ####################################################################
    ####################### Whitespace / Comments ######################
    ####################################################################
    ####################################################################

    # We pick up at state "possible_comment_-", where we read another "-", starting a comment
    transitions[('possible_comment_-', b'-', None)] = ('comment_start', 'right', 'read', None)

    # Comment! Is it the "--" form, or the "--[=*[" form?
    for c in ALL:
        transitions[('comment_start', c, None)] = ('comment_single_line', 'stay', 'read', None)
    transitions[('comment_start', b'[', None)] = \
        ('multiline_comment_or_long_string_start', 'stay', 'push', 'multiline_comment')

    # Single-line form: read until end of line, then go back to the whitespace state
    # Note: newline characters are defined as '\n' and '\r'; see currIsNewline() in llex.c
    for c in u8_complement(b'\r\n'):
        transitions[('comment_single_line', c, None)] = ('comment_single_line', 'right', 'read', None)
    # \r and \n will be consumed in read_whitespace()

    # Multi-line form. Pop our 'multline_comment' stack symbol
    # Final "]" will be consumed in read_whitespace()
    transitions[('multiline_comment_or_long_string_end', b']', 'multiline_comment')] = \
        ('comment_multiline_end', 'stay', 'pop', None)
    for c in ALL:
        transitions[('multiline_comment_or_long_string_end_opening_fail', c, 'multiline_comment')] = \
            ('comment_single_line', 'stay', 'pop', None)


    ####################################################################
    ####################################################################
    ######################### Names / Keywords #########################
    ####################################################################
    ####################################################################

    # We start in the 'name_or_keyword' state, having already verified
    # that the first character is alphabetic (but still being positioned
    # on that character).


    # ======== "name" STATE ========

    # Skip over alphanumeric characters while in the "name" state
    for c in IN_LISLALNUM:
        transitions[('name', c, None)] = ('name', 'right', 'read', None)
    # (Exiting the state when a non-alphanum character is read is
    # handled by read_name_or_keyword().)


    # ======== "name_or_keyword" STATE ========

    # If the first thing we read isn't the start of a keyword, go to the name state
    for c in IN_LISLALNUM:
        transitions[('name_or_keyword', c, None)] = ('name', 'stay', 'read', None)

    # Now we'll replace some of those to look for actual keywords.
    for keyword in KEYWORDS:
        # If we have a partial keyword on the stack, but get literally
        # anything other than what we're looking for, pop the
        # in-progress keyword off the stack and go to the name state to
        # handle it like a name
        for c in ALL:
            keyword_so_far = ''
            for k in keyword:
                keyword_so_far += k
                transitions[('name_or_keyword', c, keyword_so_far)] = ('name', 'stay', 'pop', None)

    for keyword in KEYWORDS:
        # If we complete the full keyword and encounter something
        # non-alphanumeric, go to the appropriate keyword state
        for c in NOT_LISLALNUM:
            transitions[('name_or_keyword', c, keyword)] = ('keyword_' + keyword, 'stay', 'pop', None)
        # (read_name_or_keyword() takes it from here.)

        # Actual primary sequence of transitions for the keyword
        transitions[('name_or_keyword', keyword[0].encode('cp1252'), None)] = ('name_or_keyword', 'right', 'push', keyword[0])

        keyword_so_far = keyword[0]
        for c in keyword[1:]:
            transitions[('name_or_keyword', c.encode('cp1252'), keyword_so_far)] = ('name_or_keyword', 'right', 'replace', keyword_so_far + c)
            keyword_so_far += c


    ####################################################################
    ####################################################################
    ############################# Name List ############################
    ####################################################################
    ####################################################################

    # Read a name
    read_name_or_keyword('name_list_start',
        ('name_list_entry_end', 'stay', 'read', None),    # (read an actual name)
        ('name_list_exit_keyword', 'stay', 'read', None)) # (read a keyword)

    # If we read an actual name, either read a comma and read a second name,
    # or go to the exit state
    for c in ALL:
        transitions[('name_list_entry_end', c, None)] = ('name_list_exit_name', 'stay', 'read', None)
    read_whitespace('name_list_entry_end', FAIL_TRANSITION)
    transitions[('name_list_entry_end', b',', None)] = ('name_list_start_2', 'right', 'read', None)
    read_whitespace('name_list_start_2', FAIL_TRANSITION)

    # Read another name (2nd, 3rd, 4th, etc)
    # This time, we fail immediately if we discover a keyword
    read_name_or_keyword('name_list_start_2',
        ('name_list_entry_end', 'stay', 'read', None), # (read an actual name)
        FAIL_TRANSITION)                               # (read a keyword)


    ####################################################################
    ####################################################################
    ########################## Function Bodies #########################
    ####################################################################
    ####################################################################

    # To enter this subsystem:
    # - push something you can use to later return on the stack
    # - transition to state "func_body_start"
    #   (whitespace will be taken care of for you)
    # To exit:
    # - make a transition from "func_body_end" back
    #   to your own state, which checks for your stack value and pops it
    #   (will be right after the "end" is parsed, so transition on all
    #   characters)

    # Note about a requirement for the implementation below:
    # Make sure to treat a failed closing "]" as the possible start of
    # the real ending; that is, account for "code() --[===[ comment ]=]===] code()"

    read_whitespace('func_body_start', FAIL_TRANSITION)

    # Read a "(", and then whitespace
    transitions[('func_body_start', b'(', None)] = ('parlist_start', 'right', 'read', None)
    read_whitespace('parlist_start', FAIL_TRANSITION)

    # Read a name, and then whitespace
    read_name_or_keyword('parlist_start', ('parlist_after_name', 'stay', 'read', None), FAIL_TRANSITION)
    read_whitespace('parlist_after_name', FAIL_TRANSITION)

    # Read a comma, and then whitespace
    transitions[('parlist_after_name', b',', None)] = ('parlist_after_comma', 'right', 'read', None)
    read_whitespace('parlist_after_comma', FAIL_TRANSITION)

    # We can read another name now, and then loop back
    read_name_or_keyword('parlist_after_comma', ('parlist_after_name', 'stay', 'read', None), FAIL_TRANSITION)

    # If we see a "." right after the opening "(" or after a comma, start trying to read a full "..."
    transitions[('parlist_start', b'.', None)] = ('parlist_.', 'right', 'read', None)
    transitions[('parlist_after_comma', b'.', None)] = ('parlist_.', 'right', 'read', None)
    transitions[('parlist_.', b'.', None)] = ('parlist_..', 'right', 'read', None)
    transitions[('parlist_..', b'.', None)] = ('parlist_...', 'right', 'read', None)
    # (possibly followed by whitespace)
    read_whitespace('parlist_...', FAIL_TRANSITION)

    # If we see a ")" after the opening "(", a name, or the "...", start reading statements
    transitions[('parlist_start', b')', None)] = ('statement', 'right', 'push', 'func_body')
    transitions[('parlist_after_name', b')', None)] = ('statement', 'right', 'push', 'func_body')
    transitions[('parlist_...', b')', None)] = ('statement', 'right', 'push', 'func_body')
    
    # The rest is handled by the 'func_body': 'func_body_end' entry in
    # STACK_VALUES_POPPED_BY_END_KEYWORD


    ####################################################################
    ####################################################################
    ####################### Short String Literals ######################
    ####################################################################
    ####################################################################

    # To enter this subsystem:
    # - push something you can use to later return on the stack
    # - transition to state "short_string_start"
    # To exit:
    # - make a transition from "short_string_end" back
    #   to your own state, which checks for your stack value and pops it
    #
    # Leading/trailing whitespace is NOT handled here.

    transitions[('short_string_start', b"'", None)] = ('short_string', 'right', 'push', "'")
    transitions[('short_string_start', b'"', None)] = ('short_string', 'right', 'push', '"')

    # Looking at llex.c, it seems that the only things that can cause a
    # string to be malformed are:
    # - unescaped newline (\n or \r)
    # - malformed escape sequence
    # - EOF

    # Almost all characters should be read as normal
    for c in u8_complement(b'\r\n\\'):
        transitions[('short_string', c, None)] = ('short_string', 'right', 'read', None)

    # Allow embedding the opposite quote character
    transitions[('short_string', b'"', "'")] = ('short_string', 'right', 'read', None)
    transitions[('short_string', b"'", '"')] = ('short_string', 'right', 'read', None)

    # Detect start of an escape sequence
    transitions[('short_string', b'\\', None)] = ('short_string_esc_seq', 'right', 'read', None)

    # Easy single-character ones
    for c in bstr_to_set(b'abfnrtv' b'\\' b'"' b"'" b'\n'):
        transitions[('short_string_esc_seq', c, None)] = ('short_string', 'right', 'read', None)

    # \z: skips all following whitespace characters including linebreaks.
    # NOTE: that means IN_LISSPACE, not read_whitespace() (which would
    # skip over Lua comments)
    transitions[('short_string_esc_seq', b'z', None)] = ('short_string_esc_seq_z', 'right', 'read', None)
    for c in IN_LISSPACE:
        transitions[('short_string_esc_seq_z', c, None)] = ('short_string_esc_seq_z', 'right', 'read', None)
    for c in NOT_LISSPACE:
        transitions[('short_string_esc_seq_z', c, None)] = ('short_string', 'stay', 'read', None)

    # \xXX: hexadecimal literal
    transitions[('short_string_esc_seq', b'x', None)] = ('short_string_esc_seq_x', 'right', 'read', None)
    for c in HEX_DIGITS:
        transitions[('short_string_esc_seq_x', c, None)] = ('short_string_esc_seq_x_X', 'right', 'read', None)
        transitions[('short_string_esc_seq_x_X', c, None)] = ('short_string', 'right', 'read', None)

    # \d, \dd, \ddd: decimal literal
    # This is tricky for two reasons:
    # - This can be 1, 2 or 3 digits long
    # - We have to detect and reject \256 and above
    # Notes:
    # - Lua reads \dddd as \ddd followed by a digit character

    # If the first digit is 0 or 1, no overflow potential
    for d in bstr_to_set(b'01'):
        transitions[('short_string_esc_seq', d, None)] = ('short_string_esc_seq_01', 'right', 'read', None)
    for d in DIGITS:
        transitions[('short_string_esc_seq_01', d, None)] = ('short_string_esc_seq_01_*', 'right', 'read', None)
        transitions[('short_string_esc_seq_01_*', d, None)] = ('short_string', 'right', 'read', None)
    for c in u8_complement(DIGITS):
        transitions[('short_string_esc_seq_01', c, None)] = ('short_string', 'stay', 'read', None)
        transitions[('short_string_esc_seq_01_*', c, None)] = ('short_string', 'stay', 'read', None)

    # If the first digit is 3-9, it will overflow iff the escape is 3 digits long
    for d in bstr_to_set(b'3456789'):
        transitions[('short_string_esc_seq', d, None)] = ('short_string_esc_seq_3-9', 'right', 'read', None)
    for d in DIGITS:
        transitions[('short_string_esc_seq_3-9', d, None)] = ('short_string_esc_seq_3-9_*', 'right', 'read', None)
    for c in u8_complement(DIGITS):
        transitions[('short_string_esc_seq_3-9', c, None)] = ('short_string', 'stay', 'read', None)
        transitions[('short_string_esc_seq_3-9_*', c, None)] = ('short_string', 'stay', 'read', None)

    # If the first digit is 2, it *might* overflow depending on the following digits,
    # so separate it into "2_0-4", "2_5", and "2_6-9" categories
    transitions[('short_string_esc_seq', b'2', None)] = ('short_string_esc_seq_2', 'right', 'read', None)
    for d in bstr_to_set(b'01234'): # Second digit is 0-4: no overflow potential
        transitions[('short_string_esc_seq_2', d, None)] = ('short_string_esc_seq_2_0-4', 'right', 'read', None)
    transitions[('short_string_esc_seq_2', b'5', None)] = ('short_string_esc_seq_2_5', 'right', 'read', None)
    for d in bstr_to_set(b'6789'): # Second digit is 6-9: will overflow iff escape is 3 digits long
        transitions[('short_string_esc_seq_2', d, None)] = ('short_string_esc_seq_2_6-9', 'right', 'read', None)
    for c in u8_complement(DIGITS):
        transitions[('short_string_esc_seq_2', c, None)] = ('short_string', 'stay', 'read', None)

    # Handle the easy "2_0-4" and "2_6-9" cases from above
    for d in DIGITS:
        transitions[('short_string_esc_seq_2_0-4', d, None)] = ('short_string', 'right', 'read', None)
    for c in u8_complement(DIGITS):
        transitions[('short_string_esc_seq_2_0-4', c, None)] = ('short_string', 'stay', 'read', None)
        transitions[('short_string_esc_seq_2_6-9', c, None)] = ('short_string', 'stay', 'read', None)

    # Handle the more complicated case where we have \25[something]
    for d in bstr_to_set(b'012345'): # only valid digits to follow \25
        transitions[('short_string_esc_seq_2_5', d, None)] = ('short_string', 'right', 'read', None)
    for c in u8_complement(DIGITS):
        transitions[('short_string_esc_seq_2_5', c, None)] = ('short_string', 'stay', 'read', None)

    # \u{XXX}: Unicode  literal
    # Notes:
    # - Values greater than 7FFFFFFF are forbidden
    # - No limit to the total number of digits (e.g. "\u{0000000007FFFFFFF}" is fine)
    # - Must have at least one digit (i.e. "\u{}" is invalid)

    transitions[('short_string_esc_seq', b'u', None)] = ('short_string_esc_seq_u', 'right', 'read', None)
    transitions[('short_string_esc_seq_u', b'{', None)] = ('short_string_esc_seq_u{', 'right', 'read', None)

    # Step 1: skip over all leading zeros
    transitions[('short_string_esc_seq_u{', b'0', None)] = ('short_string_esc_seq_u{_0', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_0', b'0', None)] = ('short_string_esc_seq_u{_0', 'right', 'read', None)
    # Step 2: differentiate based on initial character 1-7 vs 8-F
    for d in bstr_to_set(b'1234567'):
        transitions[('short_string_esc_seq_u{', d, None)] = ('short_string_esc_seq_u{_1-7', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_0', d, None)] = ('short_string_esc_seq_u{_1-7', 'right', 'read', None)
    for d in bstr_to_set(b'89') | ONLY_HEX_DIGITS:
        transitions[('short_string_esc_seq_u{', d, None)] = ('short_string_esc_seq_u{_8-F', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_0', d, None)] = ('short_string_esc_seq_u{_8-F', 'right', 'read', None)
    # Step 3 (if first nonzero digit was 1-7): read up to 7 more chars
    for d in HEX_DIGITS:
        transitions[('short_string_esc_seq_u{_1-7', d, None)] = ('short_string_esc_seq_u{_1-7_+1', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_1-7_+1', d, None)] = ('short_string_esc_seq_u{_1-7_+2', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_1-7_+2', d, None)] = ('short_string_esc_seq_u{_1-7_+3', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_1-7_+3', d, None)] = ('short_string_esc_seq_u{_1-7_+4', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_1-7_+4', d, None)] = ('short_string_esc_seq_u{_1-7_+5', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_1-7_+5', d, None)] = ('short_string_esc_seq_u{_1-7_+6', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_1-7_+6', d, None)] = ('short_string_esc_seq_u{_1-7_+7', 'right', 'read', None)
    # Step 3 (if first nonzero digit was 8-F): read up to 6 more chars
    for d in HEX_DIGITS:
        transitions[('short_string_esc_seq_u{_8-F', d, None)] = ('short_string_esc_seq_u{_8-F_+1', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_8-F_+1', d, None)] = ('short_string_esc_seq_u{_8-F_+2', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_8-F_+2', d, None)] = ('short_string_esc_seq_u{_8-F_+3', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_8-F_+3', d, None)] = ('short_string_esc_seq_u{_8-F_+4', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_8-F_+4', d, None)] = ('short_string_esc_seq_u{_8-F_+5', 'right', 'read', None)
        transitions[('short_string_esc_seq_u{_8-F_+5', d, None)] = ('short_string_esc_seq_u{_8-F_+6', 'right', 'read', None)
    # Step 4: read "}" from states that should allow it
    transitions[('short_string_esc_seq_u{_0', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7_+1', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7_+2', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7_+3', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7_+4', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7_+5', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7_+6', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_1-7_+7', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_8-F', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_8-F_+1', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_8-F_+2', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_8-F_+3', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_8-F_+4', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_8-F_+5', b'}', None)] = ('short_string', 'right', 'read', None)
    transitions[('short_string_esc_seq_u{_8-F_+6', b'}', None)] = ('short_string', 'right', 'read', None)

    # Detect end
    transitions[('short_string', b"'", "'")] = ('short_string_end', 'right', 'pop', None)
    transitions[('short_string', b'"', '"')] = ('short_string_end', 'right', 'pop', None)


    ####################################################################
    ####################################################################
    ######################## Table Constructors ########################
    ####################################################################
    ####################################################################

    # To enter this subsystem:
    # - push something you can use to later return on the stack
    # - transition to state "table_constructor_start"
    # To exit:
    # - make a transition from "table_constructor_end" back
    #   to your own state, which checks for your stack value and pops it
    #
    # Leading/trailing whitespace is NOT handled here.

    transitions[('table_constructor_start', b'{', None)] = ('table_constructor_whitespace_before_field', 'right', 'read', None)

    # ======== Whitespace before field ========

    # Note: if read_whitespace consumes a "-", that's OK (e.g.
    # "a = {-23}"), but the field that follows HAS to be of the
    # "field ::= exp" form. (Sub-note: "exp ::= '-' exp" is a correct rule.)
    for c in ALL:
        transitions[('table_constructor_whitespace_before_field', c, None)] = ('table_constructor_before_field', 'stay', 'read', None)
    read_whitespace('table_constructor_whitespace_before_field',
        ('table_constructor_before_field_-', 'stay', 'read', None))

    # ======== "field ::= ‘[’ exp ‘]’ ‘=’ exp" ========

    # Note: just because we get a [ as the first character DOESN'T mean
    # it's actually "field ::= ‘[’ exp ‘]’ ‘=’ exp", because maybe it's
    # like "a = {[[long string expression]]}". So we have to check the
    # next character, and respond accordingly.

    for c in ALL:
        transitions[('table_constructor_before_field', c, None)] = ('table_constructor_field_[', 'right', 'read', None)
    for c in u8_complement(b'[='):
        transitions[('table_constructor_field_[', c, None)] = ('table_constructor_field_[_before_exp', 'stay', 'read', None)
    transitions[('table_constructor_field_[', b'[', None)] = ('table_constructor_field_[[_or_[=', 'stay', 'read', None)
    transitions[('table_constructor_field_[', b'=', None)] = ('table_constructor_field_[[_or_[=', 'stay', 'read', None)

    # field ::= exp      WHERE exp is a long-form string literal
    transitions[('table_constructor_field_[[_or_[=', b'[', None)] = ('multiline_comment_or_long_string_start_2', 'stay', 'push', 'table_constructor_long_string_field_exp')
    transitions[('table_constructor_field_[[_or_[=', b'=', None)] = ('multiline_comment_or_long_string_start_2', 'stay', 'push', 'table_constructor_long_string_field_exp')
    transitions[('multiline_comment_or_long_string_end', b']', 'table_constructor_long_string_field_exp')] = \
        ('table_constructor_field_after_name_or_exp_before_whitespace', 'right', 'push', 'not_only_name')
    for c in ALL:
        transitions[('table_constructor_field_after_name_or_exp_before_whitespace', c, None)] = ('table_constructor_field_after_name_or_exp', 'stay', 'read', None)
    read_whitespace('table_constructor_field_after_name_or_exp_before_whitespace',
        FAIL_TRANSITION) # TODO: ...this technically wouldn't be a syntax error, right?
    # (^ push 'not_only_name' to match the result of the
    #  check_if_only_name=True in the read_expression() call that
    #  normally takes the parser to the table_constructor_field_after_name_or_exp state)

    # field ::= ‘[’ exp ‘]’ ‘=’ exp
    read_expression('table_constructor_field_[_before_exp',
        ('table_constructor_field_[_exp', 'stay', 'read', None))
    transitions[('table_constructor_field_[_exp', b']', None)] = ('table_constructor_field_[_exp_]', 'right', 'read', None)
    read_whitespace('table_constructor_field_[_exp_]', FAIL_TRANSITION)
    transitions[('table_constructor_field_[_exp_]', b'=', None)] = ('table_constructor_field_[_exp_]_=', 'right', 'read', None)
    read_expression('table_constructor_field_[_exp_]_=',
        ('table_constructor_field_[_exp_]_=_exp', 'stay', 'read', None))
    transitions[('table_constructor_field_[_exp_]_=_exp', b',', None)] = ('table_constructor_whitespace_before_field', 'right', 'read', None)
    transitions[('table_constructor_field_[_exp_]_=_exp', b';', None)] = ('table_constructor_whitespace_before_field', 'right', 'read', None)

    # ======== "field ::= Name ‘=’ exp" AND "field ::= exp" ========

    for c in u8_complement(b'['):
        transitions[('table_constructor_before_field', c, None)] = ('table_constructor_field_name_or_exp', 'stay', 'push', 'did_not_have_minus')
        transitions[('table_constructor_before_field_-', c, None)] = ('table_constructor_field_name_or_exp', 'stay', 'push', 'had_minus')

    read_expression('table_constructor_field_name_or_exp',
        ('table_constructor_field_after_name_or_exp', 'stay', 'read', None),
        equals_transition=('table_constructor_field_after_name_or_exp_=_(1)', 'stay', 'read', None),
        check_if_only_name=True)

    # Note that we can also reach
    # table_constructor_field_after_name_or_exp by manually reading a
    # long-form string (which occurs in the previous section).

    # Handle the "equals_transition" from read_expression()

    # field ::= Name ‘=’ exp
    # (only counts if "did_not_have_minus" is on stack below "only_name")
    
    for c in ALL:
        transitions[('table_constructor_field_after_name_or_exp_=_(1)', c, 'only_name')] = ('table_constructor_field_name_=_(2)', 'stay', 'pop', None)
        transitions[('table_constructor_field_name_=_(2)', c, 'did_not_have_minus')] = ('table_constructor_field_name_=_(3)', 'stay', 'pop', None)
    read_expression('table_constructor_field_name_=_(3)',
        ('table_constructor_field_name_=_exp', 'stay', 'read', None))
    transitions[('table_constructor_field_name_=_exp', b',', None)] = ('table_constructor_whitespace_before_field', 'right', 'read', None)
    transitions[('table_constructor_field_name_=_exp', b';', None)] = ('table_constructor_whitespace_before_field', 'right', 'read', None)

    # field ::= exp
    transitions[('table_constructor_field_after_name_or_exp', b',', None)] = ('table_constructor_field_after_exp', 'stay', 'pop', None)
    transitions[('table_constructor_field_after_exp', b',', None)] = ('table_constructor_whitespace_before_field', 'right', 'pop', None)
    transitions[('table_constructor_field_after_name_or_exp', b';', None)] = ('table_constructor_field_after_exp', 'stay', 'pop', None)
    transitions[('table_constructor_field_after_exp', b';', None)] = ('table_constructor_whitespace_before_field', 'right', 'pop', None)

    # ======== Exiting ========

    transitions[('table_constructor_whitespace_before_field', b'}', None)] = ('table_constructor_end', 'right', 'read', None)
    transitions[('table_constructor_field_[_exp_]_=_exp', b'}', None)] = ('table_constructor_end', 'right', 'read', None)
    transitions[('table_constructor_field_name_=_exp', b'}', None)] = ('table_constructor_end', 'right', 'read', None)
    transitions[('table_constructor_field_after_name_or_exp', b'}', None)] = ('table_constructor_field_after_exp_}', 'stay', 'pop', None)
    transitions[('table_constructor_field_after_exp_}', b'}', None)] = ('table_constructor_end', 'right', 'pop', None)


    ####################################################################
    ####################################################################
    ######################## L-values & R-values #######################
    ####################################################################
    ####################################################################

    # ======== Entry point 1: haven't read a name yet ========

    for c in IN_LISLALPHA:
        transitions[('lrvalue_start_1', c, None)] = ('lrvalue_start_1_name_or_keyword', 'stay', 'read', None)

    transitions[('lrvalue_start_1', b'(', None)] = ('lrvalue_start_1_expression', 'right', 'read', None)
    read_expression('lrvalue_start_1_expression',
        ('lrvalue_start_1_expression_end', 'stay', 'read', None))
    _lrvalue_init_stack_state_and_read_next_part('lrvalue_start_1_expression_end', b')', 'right',
        'rvalue', 'not_only_name', 'not_function_call')

    read_name_or_keyword('lrvalue_start_1_name_or_keyword',
        ('lrvalue_start_1_name', 'stay', 'read', None),
        ('lrvalue_exit_keyword', 'stay', 'read', None))

    _lrvalue_init_stack_state_and_read_next_part('lrvalue_start_1_name', ALL, 'stay',
        'lvalue_or_rvalue', 'only_name', 'not_function_call')

    # ======== Entry point 2: already read a name ========

    _lrvalue_init_stack_state_and_read_next_part('lrvalue_start_2', ALL, 'stay',
        'lvalue_or_rvalue', 'only_name', 'not_function_call')

    # ======== "Read next part" (see "lvalue-rvalue-notes.txt") ========

    # Exit if we get an unexpected character; otherwise, read whitespace
    for c in ALL:
        transitions[('lrvalue_read_next_part', c, None)] = ('lrvalue_exit', 'stay', 'read', None)
    read_whitespace('lrvalue_read_next_part',
        ('lrvalue_-_exit', 'stay', 'read', None))

    # (similar for ":" one, except that a "-" is invalid, and we can't
    # exit without reading the function arguments after it)
    read_whitespace('lrvalue_read_next_part_:',
        FAIL_TRANSITION)

    # Switch on next character, if recognized
    transitions[('lrvalue_read_next_part'  , b'(', None)] = ('lrvalue_read_func_args_(', 'right', 'read', None)
    transitions[('lrvalue_read_next_part_:', b'(', None)] = ('lrvalue_read_func_args_(', 'right', 'read', None)
    transitions[('lrvalue_read_next_part'  , b'{', None)] = ('lrvalue_read_func_args_{', 'stay' , 'read', None)
    transitions[('lrvalue_read_next_part_:', b'{', None)] = ('lrvalue_read_func_args_{', 'stay' , 'read', None)
    transitions[('lrvalue_read_next_part'  , b"'", None)] = ('lrvalue_read_func_args_"', 'stay' , 'read', None)
    transitions[('lrvalue_read_next_part_:', b"'", None)] = ('lrvalue_read_func_args_"', 'stay' , 'read', None)
    transitions[('lrvalue_read_next_part'  , b'"', None)] = ('lrvalue_read_func_args_"', 'stay' , 'read', None)
    transitions[('lrvalue_read_next_part_:', b'"', None)] = ('lrvalue_read_func_args_"', 'stay' , 'read', None)
    transitions[('lrvalue_read_next_part'  , b'[', None)] = ('lrvalue_read_['          , 'right', 'read', None)
    transitions[('lrvalue_read_next_part_:', b'[', None)] = ('lrvalue_read_[_after_:'  , 'right', 'read', None)
    transitions[('lrvalue_read_next_part'  , b'.', None)] = ('lrvalue_read_.'          , 'right', 'read', None)
    transitions[('lrvalue_read_next_part'  , b':', None)] = ('lrvalue_read_:'          , 'right', 'read', None)

    # ======== Function arguments ========

    # ( )
    read_expression_list('lrvalue_read_func_args_(',
                         ('lrvalue_read_func_args_(_)', 'right', 'read', None), # function does not consume ")" in this case
        rparen_transition=('lrvalue_read_func_args_(_)', 'stay', 'read', None))  # function DOES consume ")" in this one, though
    _lrvalue_set_stack_state_and_read_next_part('lrvalue_read_func_args_(_)', ALL, 'stay',
        'rvalue', 'not_only_name', 'function_call')

    # { }
    transitions[('lrvalue_read_func_args_{', b'{', None)] = ('table_constructor_start', 'stay', 'push', 'lrvalue_read_func_args_{}')
    for c in ALL:
        transitions[('table_constructor_end', c, 'lrvalue_read_func_args_{}')] = ('lrvalue_read_func_args_{_}', 'stay', 'pop', None)
    _lrvalue_set_stack_state_and_read_next_part('lrvalue_read_func_args_{_}', ALL, 'stay',
        'rvalue', 'not_only_name', 'function_call')

    # ' ' or " "
    for quote in bstr_to_set(b'\'"'):
        transitions[('lrvalue_read_func_args_"', quote, None)] = ('short_string_start', 'stay', 'push', 'lrvalue_short_string')
    # (Note: the 'rvalue' was already put on the stack by read-next-part)
    for c in ALL:
        transitions[('short_string_end', c, 'lrvalue_short_string')] = ('lrvalue_read_func_args_"_"', 'stay', 'pop', None)
    _lrvalue_set_stack_state_and_read_next_part('lrvalue_read_func_args_"_"', ALL, 'stay',
        'rvalue', 'not_only_name', 'function_call')

    # ======== [ ========

    # Either a function call with a long string ( func [[string]] ) or
    # table indexing ( table[index] ). Only way to find out which one is
    # to read the next character.

    # Note: Something like "func_a[[[something]]]" could theoretically
    # be interpreted as indexing a table by a long string; however, Lua
    # itself reads it as "func_a [[ [something ]] ]", with that last "]"
    # causing a syntax error. So checking for "[[" to identify a
    # long-string argument should be correct.

    # We also REQUIRE it to be a long string rather than indexing if
    # coming from the "lrvalue_read_[_after_:" state.

    # We already went past the first '[', so, read the following
    # character now
    for c in u8_complement(b'[='):
        transitions[('lrvalue_read_[', c, None)] = ('lrvalue_read_[_membership', 'stay', 'replace', 'lvalue_or_rvalue')
    transitions[('lrvalue_read_['        , b'[', None)] = ('lrvalue_read_[[_func_args', 'stay', 'read', None)
    transitions[('lrvalue_read_[_after_:', b'[', None)] = ('lrvalue_read_[[_func_args', 'stay', 'read', None)
    transitions[('lrvalue_read_['        , b'=', None)] = ('lrvalue_read_[[_func_args', 'stay', 'read', None)
    transitions[('lrvalue_read_[_after_:', b'=', None)] = ('lrvalue_read_[[_func_args', 'stay', 'read', None)

    # ([[]] or [==[]==] long string func args)
    transitions[('lrvalue_read_[[_func_args', b'[', None)] = ('multiline_comment_or_long_string_start_2', 'stay', 'push', 'lrvalue_long_string_func_args')
    transitions[('lrvalue_read_[[_func_args', b'=', None)] = ('multiline_comment_or_long_string_start_2', 'stay', 'push', 'lrvalue_long_string_func_args')
    transitions[('multiline_comment_or_long_string_end', b']', 'lrvalue_long_string_func_args')] = \
        ('lrvalue_read_[[_func_args_]]', 'stay', 'pop', None)
    _lrvalue_set_stack_state_and_read_next_part('lrvalue_read_[[_func_args_]]', b']', 'right',
        'rvalue', 'not_only_name', 'function_call')

    # ([] table membership)
    read_expression('lrvalue_read_[_membership',
        ('lrvalue_read_[_membership_exp', 'stay', 'read', None))
    _lrvalue_set_stack_state_and_read_next_part('lrvalue_read_[_membership_exp', b']', 'right',
        'lvalue_or_rvalue', 'not_only_name', 'not_function_call')

    # ======== . ========

    # We already consumed the ".".
    for c in ALL:
        transitions[('lrvalue_read_.', c, None)] = ('lrvalue_read_._after_whitespace', 'stay', 'read', None)
    transitions[('lrvalue_read_.', b'.', None)] = ('lrvalue_._exit', 'stay', 'read', None)
    read_whitespace('lrvalue_read_.', FAIL_TRANSITION)
    read_name_or_keyword('lrvalue_read_._after_whitespace',
        ('lrvalue_read_._name', 'stay', 'read', None),
        FAIL_TRANSITION)
    _lrvalue_set_stack_state_and_read_next_part('lrvalue_read_._name', ALL, 'stay',
        'lvalue_or_rvalue', 'not_only_name', 'not_function_call')

    # ======== : ========

    # Similar to '.', except that the name *must* be followed by a
    # function call.
    for c in ALL:
        transitions[('lrvalue_read_:', c, None)] = ('lrvalue_read_:_after_whitespace', 'stay', 'read', None)
    transitions[('lrvalue_read_:', b':', None)] = ('lrvalue_:_exit', 'stay', 'read', None)
    read_whitespace('lrvalue_read_:', FAIL_TRANSITION)
    read_name_or_keyword('lrvalue_read_:_after_whitespace',
        ('lrvalue_read_:_name', 'stay', 'read', None),
        FAIL_TRANSITION)
    _lrvalue_set_stack_state_and_read_next_part('lrvalue_read_:_name', ALL, 'stay',
        'rvalue', 'not_only_name', 'function_call',
        is_colon_version=True)


    ####################################################################
    ####################################################################
    ############################ Expressions ###########################
    ####################################################################
    ####################################################################

    # Helper state that changes the check_if_only_name state to
    # 'not_only_name' and transitions to expression_end
    for c in ALL:
        transitions[('expression_binop-or-end_with_not_only_name', c, None)] = ('expression_binop-or-end', 'stay', 'replace', 'not_only_name')

    # Helper state that reads any whitespace before going back to
    # expression (used by unary operators)
    # Does NOT change the only_name/not_only_name state!
    for c in ALL:
        transitions[('expression_restart', c, None)] = ('expression', 'stay', 'read', None)
    read_whitespace('expression_restart',
        ('expression_restart', 'stay', 'read', None))
    # ^ see explanatory comment for similar code chunk at the start of
    # read_expression()

    # ======== Binary operators ========

    # Helper state that reads whitespace, and then either finds a binary
    # operator and handles appropriately, or finds something else and
    # goes to expression_exit
    for c in ALL:
        transitions[('expression_binop-or-end', c, None)] = ('expression_exit', 'stay', 'read', None)

    # Start with all of the punctuation-based ones, because those are
    # relatively easy-ish
    ONE_CHAR_BINOPS = bstr_to_set(b'+-*/^%&~|<>')
    TWO_CHAR_BINOPS = [b'//', b'>>', b'<<', b'..', b'<=', b'>=', b'==', b'~=']

    for c in ONE_CHAR_BINOPS:
        transitions[('expression_binop-or-end', c, None)] = ('expression_restart', 'right', 'replace', 'not_only_name')

    for c1, c2 in TWO_CHAR_BINOPS:
        c1, c2 = bytes([c1]), bytes([c2])
        transitions[('expression_binop-or-end', c1, None)] = ('expression_binop_' + c1.decode('cp1252'), 'right', 'read', None)
        transitions[('expression_binop_' + c1.decode('cp1252'), c2, None)] = ('expression_restart', 'right', 'replace', 'not_only_name')

        if c1 in ONE_CHAR_BINOPS:
            all_c2s_for_this_c1 = set(bytes([bo[1]]) for bo in TWO_CHAR_BINOPS if bytes([bo[0]]) == c1)
            for c in u8_complement(all_c2s_for_this_c1):
                transitions[('expression_binop_' + c1.decode('cp1252'), c, None)] = ('expression_restart', 'stay', 'replace', 'not_only_name')

    for c in u8_complement(b'='):
        transitions[('expression_binop_=', c, None)] = ('expression_exit_=', 'stay', 'read', None)

    # "and" / "or"...
    transitions[('expression_binop-or-end', b'a', None)] = ('expression_binop_andoror', 'stay', 'read', None)
    transitions[('expression_binop-or-end', b'o', None)] = ('expression_binop_andoror', 'stay', 'read', None)
    read_name_or_keyword('expression_binop_andoror',
        ('expression_exit_trailing_name', 'stay', 'read', None),    # (read a name)
        ('expression_binop_andoror_keyword', 'stay', 'read', None)) # (read a keyword)
    for c in ALL:
        transitions[('expression_binop_andoror_keyword', c, 'and')] = ('expression_binop_and', 'stay', 'pop', None)
        transitions[('expression_binop_and', c, None)] = ('expression_restart', 'stay', 'replace', 'not_only_name')
        transitions[('expression_binop_andoror_keyword', c, 'or')] = ('expression_binop_or', 'stay', 'pop', None)
        transitions[('expression_binop_or', c, None)] = ('expression_restart', 'stay', 'replace', 'not_only_name')

    # (And add a read_whitespace() call to the expression_binop-or-end state.)
    read_whitespace('expression_binop-or-end', ('expression_restart', 'stay', 'replace', 'not_only_name'))

    # ======== Expressions that start with a name or keyword ========

    read_name_or_keyword('expression',
        ('expression_starting_with_name', 'stay', 'read', None),
        ('expression_starting_with_keyword', 'stay', 'read', None))

    # ======== Expressions that start with a name ========

    read_lvalue_or_rvalue('expression_starting_with_name', True,
        ('expression_after_lrvalue', 'stay', 'read', None),
        ('expression_after_lrvalue_-', 'stay', 'read', None),
        ('expression_after_lrvalue_.', 'stay', 'read', None),
        ('expression_after_lrvalue_:', 'stay', 'read', None),
        check_if_only_name=True)

    # Handle the check_if_only_name stuff appropriately
    for c in ALL:
        for has_colon in [False, True]:
            ealrv = 'expression_after_lrvalue' + ('_:' if has_colon else '')

            # Normal and colon exits from read_lvalue_or_rvalue()

            # We don't care about rvalue vs lvalue_or_rvalue
            transitions[(ealrv, c, None)] = \
                (f'{ealrv}_2', 'stay', 'pop', None)

            # Check what the "only_name" vs "not_only_name" state from
            # read_lvalue_or_rvalue was
            transitions[(f'{ealrv}_2', c, 'only_name')] = \
                (f'{ealrv}__only_name', 'stay', 'pop', None)
            transitions[(f'{ealrv}_2', c, 'not_only_name')] = \
                (f'{ealrv}__not_only_name', 'stay', 'pop', None)

            # Compare that to our own, and combine appropriately
            target = 'expression_exit_:' if has_colon else 'expression_binop-or-end'
            transitions[(f'{ealrv}__only_name', c, 'beginning')] = \
                (target, 'stay', 'replace', 'only_name')
            transitions[(f'{ealrv}__only_name', c, None)] = \
                (target, 'stay', 'replace', 'not_only_name')
            transitions[(f'{ealrv}__not_only_name', c, None)] = \
                (target, 'stay', 'replace', 'not_only_name')

        # "-" and "." exits from read_lvalue_or_rvalue()
        for mod in ['_-', '_.']:
            # We don't care about rvalue vs lvalue_or_rvalue
            transitions[(f'expression_after_lrvalue{mod}', c, None)] = \
                (f'expression_after_lrvalue{mod}_2', 'stay', 'pop', None)

            # Nor do we care about "only_name" vs "not_only_name"
            transitions[(f'expression_after_lrvalue{mod}_2', c, None)] = \
                (f'expression_after_lrvalue{mod}_3', 'stay', 'pop', None)

        # For "-", we've already consumed the whole binop, so just go
        # to expression_restart right away.
        transitions[('expression_after_lrvalue_-_3', c, None)] = \
            ('expression_restart', 'stay', 'replace', 'not_only_name')

        # For ".", only go to expression_restart if we can consume
        # another "." (to form the ".." binop)
        transitions[('expression_after_lrvalue_._3', b'.', None)] = \
            ('expression_restart', 'right', 'replace', 'not_only_name')

    # ======== Expressions that start with a keyword ========

    for c in NOT_LISLALNUM:
        transitions[('expression_starting_with_keyword', c, 'nil')] = ('expression_binop-or-end_with_not_only_name', 'stay', 'pop', None)
        transitions[('expression_starting_with_keyword', c, 'false')] = ('expression_binop-or-end_with_not_only_name', 'stay', 'pop', None)
        transitions[('expression_starting_with_keyword', c, 'true')] = ('expression_binop-or-end_with_not_only_name', 'stay', 'pop', None)
        transitions[('expression_starting_with_keyword', c, 'end')] = ('expression_exit_end', 'stay', 'pop', None)
        transitions[('expression_starting_with_keyword', c, 'elseif')] = ('expression_exit_elseif', 'stay', 'pop', None)
        transitions[('expression_starting_with_keyword', c, 'else')] = ('expression_exit_else', 'stay', 'pop', None)
        transitions[('expression_starting_with_keyword', c, 'until')] = ('expression_exit_until', 'stay', 'pop', None)
        transitions[('expression_starting_with_keyword', c, 'function')] = ('func_body_start', 'stay', 'replace', 'expression_function')
        transitions[('expression_starting_with_keyword', c, 'not')] = ('expression_not', 'stay', 'pop', None) # unary "not"
        transitions[('expression_not', c, None)] = ('expression_restart', 'stay', 'replace', 'not_only_name')

    # ======== Expressions that start with punctuation ========

    # (Not real expressions, but, things we need to handle regardless)
    transitions[('expression', b';', 'beginning')] = ('expression_exit_;', 'right', 'read', None)
    transitions[('expression', b')', 'beginning')] = ('expression_exit_)', 'right', 'read', None)

    # "..." expression
    transitions[('expression', b'.', None)] = ('expression_.', 'right', 'replace', 'not_only_name')
    transitions[('expression_.', b'.', None)] = ('expression_..', 'right', 'read', None)
    transitions[('expression_..', b'.', None)] = ('expression_binop-or-end', 'right', 'read', None)

    # "." can also be the start of a numeral expression (implied leading "0")
    for d in DIGITS:
        transitions[('expression_.', d, None)] = ('expression_numeric_after_.', 'right', 'push', 'number_dec')

    # Table constructor expression
    transitions[('expression', b'{', None)] = ('table_constructor_start', 'stay', 'push', 'expression_table_constructor')
    for c in ALL:
        transitions[('table_constructor_end', c, 'expression_table_constructor')] = ('expression_table_constructor_end', 'stay', 'pop', None)
        transitions[('expression_table_constructor_end', c, None)] = ('expression_binop-or-end', 'stay', 'replace', 'not_only_name')

    # Expression starting with '(': handle as LRvalue
    # We have to detect if the value on top of the stack is "beginning"
    # or not, and set the "already_read_name" argument to
    # read_lvalue_or_rvalue() accordingly. (The two calls are otherwise
    # identical. (If not, that's a bug.))
    transitions[('expression', b'(', None)] = ('expression_(', 'stay', 'read', None)
    read_lvalue_or_rvalue('expression_(', False,
        ('expression_after_lrvalue', 'stay', 'read', None),
        ('expression_after_lrvalue_-', 'stay', 'read', None),
        ('expression_after_lrvalue_.', 'stay', 'read', None),
        ('expression_after_lrvalue_:', 'stay', 'read', None),
        check_if_only_name=True) # it won't be, but, for consistency

    # These unary operators can be consumed without affecting anything,
    # since "exp ::= unop exp" is a valid grammar rule
    transitions[('expression', b'-', None)] = ('expression_restart', 'right', 'replace', 'not_only_name')
    transitions[('expression', b'#', None)] = ('expression_restart', 'right', 'replace', 'not_only_name')
    transitions[('expression', b'~', None)] = ('expression_restart', 'right', 'replace', 'not_only_name')

    # ======== Numerals ========

    # Detect the start of a numeric expression, but keep track of a leading 0 separately for now
    # (Note: the Lua parser uses hardcoded Arabic numeral characters here, too)
    for c in DIGITS:
        transitions[('expression', c, None)] = ('expression_starting_with_digit', 'stay', 'replace', 'not_only_name')

        transitions[('expression_starting_with_digit', c, None)] = ('expression_numeric', 'right', 'push', 'number_dec')
    transitions[('expression_starting_with_digit', b'0', None)] = ('expression_0', 'right', 'push', 'number_dec')

    # Check for hexadecimality, and be sure to consume at least one hex digit
    transitions[('expression_0', b'x', None)] = ('expression_0x', 'right', 'replace', 'number_hex')
    transitions[('expression_0', b'X', None)] = ('expression_0x', 'right', 'replace', 'number_hex')
    for c in HEX_DIGITS:
        transitions[('expression_0x', c, None)] = ('expression_numeric', 'right', 'read', None)

    # Handle numbers that start with 0 but aren't hex
    for c in DIGITS:
        transitions[('expression_0', c, None)] = ('expression_numeric', 'right', 'read', None)

    # Either way, we're now in the expression_numeric stage,
    # with either number_dec or number_hex on the stack,
    # and already having consumed one digit (so from this point we should accept 0 or more).
    for c in DIGITS:
        transitions[('expression_numeric', c, None)] = ('expression_numeric', 'right', 'read', None)
    for c in ONLY_HEX_DIGITS:
        transitions[('expression_numeric', c, 'number_hex')] = ('expression_numeric', 'right', 'read', None)

    # If we encounter a ".", read it (in a way that ensures we can only read one of them),
    # and then read zero or more digits.
    # Note that zero digits following the . is fine; e.g. "35." and "0x3E.P2" are valid.
    for pre_state in ['expression_0', 'expression_0x', 'expression_numeric']:
        transitions[(pre_state, b'.', None)] = ('expression_numeric_after_.', 'right', 'read', None)
    for c in DIGITS:
        transitions[('expression_numeric_after_.', c, None)] = ('expression_numeric_after_.', 'right', 'read', None)
    for c in ONLY_HEX_DIGITS:
        transitions[('expression_numeric_after_.', c, 'number_hex')] = ('expression_numeric_after_.', 'right', 'read', None)

    # If we find an exponent marker ("e"/"E" for decimal, "p"/"P" for hex), read it
    for pre_state in ['expression_0', 'expression_numeric', 'expression_numeric_after_.']:
        transitions[(pre_state, b'e', 'number_dec')] = ('expression_numeric_exp', 'right', 'read', None)
        transitions[(pre_state, b'E', 'number_dec')] = ('expression_numeric_exp', 'right', 'read', None)
        transitions[(pre_state, b'p', 'number_hex')] = ('expression_numeric_exp', 'right', 'read', None)
        transitions[(pre_state, b'P', 'number_hex')] = ('expression_numeric_exp', 'right', 'read', None)

    # Exponent marker is optionally followed by a + or -, and then one or more digits.
    transitions[('expression_numeric_exp', b'+', None)] = ('expression_numeric_exp_+-', 'right', 'read', None)
    transitions[('expression_numeric_exp', b'-', None)] = ('expression_numeric_exp_+-', 'right', 'read', None)

    # Regardless of presence/absence of +-, make sure we read at least one following digit...
    # (Note that digits following the exponent marker HAVE to be decimal, regardless
    # of this number's overall base.)
    for c in DIGITS:
        transitions[('expression_numeric_exp', c, None)] = ('expression_numeric_exp_value', 'right', 'read', None)
        transitions[('expression_numeric_exp_+-', c, None)] = ('expression_numeric_exp_value', 'right', 'read', None)

    # ...and then zero or more digits following that one
    for c in DIGITS:
        transitions[('expression_numeric_exp_value', c, None)] = ('expression_numeric_exp_value', 'right', 'read', None)

    # There are a few places that are valid to exit from, if we read something non-alphanumeric (other than ".")
    # We have to pop the "number_dec" or "number_hex" from the stack, now, also
    for stateToExitFrom in ['expression_0', 'expression_numeric', 'expression_numeric_after_.', 'expression_numeric_exp_value']:
        for c in without(NOT_LISLALNUM, b'.'):
            transitions[(stateToExitFrom, c, None)] = ('expression_binop-or-end', 'stay', 'pop', None)


    # ======== Short literal strings ========

    for quote in bstr_to_set(b'\'"'):
        transitions[('expression', quote, None)] = ('expression_starting_with_quote', 'stay', 'replace', 'not_only_name')
        transitions[('expression_starting_with_quote', quote, None)] = ('short_string_start', 'stay', 'push', 'expression_short_string')

    # (goes through short-string subsystem, and then...)

    for c in ALL:
        transitions[('short_string_end', c, 'expression_short_string')] = ('expression_binop-or-end', 'stay', 'pop', None)


    # ======== Long strings ========

    transitions[('expression', b'[', None)] = ('expression_starting_with_[', 'stay', 'replace', 'not_only_name')
    transitions[('expression_starting_with_[', b'[', None)] = ('multiline_comment_or_long_string_start', 'stay', 'push', 'long_string')

    transitions[('multiline_comment_or_long_string_end', b']', 'long_string')] = \
        ('expression_binop-or-end', 'right', 'pop', None)


    # ======== Function expressions ========

    # We already went through the func_body subsystem, and just have to
    # transition back.
    for c in ALL:
        transitions[('func_body_end', c, 'expression_function')] = ('expression_after_func_body', 'stay', 'pop', None)
        transitions[('expression_after_func_body', c, None)] = ('expression_binop-or-end', 'stay', 'replace', 'not_only_name')


    ####################################################################
    ####################################################################
    ######################### Expression Lists #########################
    ####################################################################
    ####################################################################

    # Read an expression
    read_expression('expression_list_start',
        ('expression_list_entry_end', 'stay', 'read', None),          # (read an actual expression)
        ('expression_list_exit_end', 'stay', 'read', None),           # (read an "end")
        ('expression_list_exit_elseif', 'stay', 'read', None),        # (read an "elseif")
        ('expression_list_exit_else', 'stay', 'read', None),          # (read an "else")
        ('expression_list_exit_until', 'stay', 'read', None),         # (read an "until")
        ('expression_list_exit_;', 'stay', 'read', None),             # (read a ";")
        ('expression_list_exit_)', 'stay', 'read', None),             # (read a ")")
        FAIL_TRANSITION,                                              # (read a "=")
        ('expression_list_exit_trailing_name', 'stay', 'read', None), # (read a trailing name)
        ('expression_list_exit_:', 'stay', 'read', None))             # (read a ":")

    # If we read an actual expression, either read a comma and read a second expression,
    # or go to the exit state
    for c in ALL:
        transitions[('expression_list_entry_end', c, None)] = ('expression_list_exit', 'stay', 'read', None)
    transitions[('expression_list_entry_end', b',', None)] = ('expression_list_start_2', 'right', 'read', None)

    # Read another expression (2nd, 3rd, 4th, etc)
    # This time, we fail immediately if we discover most things.
    read_expression('expression_list_start_2',
        ('expression_list_entry_end', 'stay', 'read', None),
        trailing_name_transition=('expression_list_exit_trailing_name', 'stay', 'read', None))


    ####################################################################
    ####################################################################
    ############################ Statements ############################
    ####################################################################
    ####################################################################

    # Based on statement() in lparser.c.

    for c in ALL:
        transitions[('block', c, None)] = ('statement', 'stay', 'push', 'block')

    # {value_on_top_of_stack: destination_state_after_reading_end_keyword}
    STACK_VALUES_POPPED_BY_END_KEYWORD = {
        'statement_do': 'statement',
        'statement_while': 'statement',
        'statement_if': 'statement',
        'statement_for': 'statement',
        'func_body': 'func_body_end',
    }

    # Ignore whitespace between statements.
    # Note: no valid statement starts with a "-".
    read_whitespace('statement', FAIL_TRANSITION)

    # ======== Statements that start with punctuation ========

    # Empty statement:
    # case ';': {  /* stat -> ';' (empty statement) */
    transitions[('statement', b';', None)] = ('statement', 'right', 'read', None)

    # Label statement:
    # case TK_DBCOLON: {  /* stat -> label */
    # NOTE: the 'statement_dbcolon_:' state can be entered directly by
    # various transitions that accidentally consume the first colon
    transitions[('statement', b':', None)] = ('statement_dbcolon_:', 'right', 'read', None)
    transitions[('statement_dbcolon_:', b':', None)] = ('statement_dbcolon_::', 'right', 'read', None)
    read_whitespace('statement_dbcolon_::', FAIL_TRANSITION)
    read_name_or_keyword('statement_dbcolon_::',
        ('statement_dbcolon_::NAME', 'stay', 'read', None),
        FAIL_TRANSITION)
    read_whitespace('statement_dbcolon_::NAME', FAIL_TRANSITION)
    transitions[('statement_dbcolon_::NAME', b':', None)] = ('statement_dbcolon_::NAME:', 'right', 'read', None)
    transitions[('statement_dbcolon_::NAME:', b':', None)] = ('statement', 'right', 'read', None)

    # A statement that starts with a '(' is an assignment statement
    transitions[('statement', b'(', None)] = ('statement_(', 'stay', 'read', None)
    read_lvalue_or_rvalue('statement_(', False,
        ('statement_read_lvalue_hopefully', 'stay', 'read', None),
        FAIL_TRANSITION, # "(a) - b" (or similar) would never be a valid start to a statement
        FAIL_TRANSITION, # "(a) .. b" (or similar) would never be a valid start to a statement
        FAIL_TRANSITION, # "(a) ::Label::" (or similar) would never be a valid start to a statement
        check_if_function_call=True)

    # ======== Statements that start with a name ========

    # Set up transitions for reading either a name or a keyword
    read_name_or_keyword('statement',
        ('statement_starting_with_name', 'stay', 'read', None),
        ('statement_starting_with_keyword', 'stay', 'read', None))

    read_whitespace('statement_starting_with_name', FAIL_TRANSITION)

    # Once we've read a name, there are two possibilities for what the
    # statement might be:
    # stat ::= varlist ‘=’ explist
    # OR
    # stat ::= functioncall

    # -------- Distinguishing between assignment statements and function calls --------

    # The next thing to do, then, is to read the rest of this as an
    # lvalue. (Unless a ',' or '=' comes next, in which case we know
    # it's definitely an assignment statement.)

    transitions[('statement_starting_with_name', b',', None)] = ('statement_assign_varlist', 'right', 'read', None)
    transitions[('statement_starting_with_name', b'=', None)] = ('statement_assign_rightside', 'right', 'read', None)

    read_lvalue_or_rvalue('statement_starting_with_name', True,
        ('statement_read_lvalue_hopefully', 'stay', 'read', None),
        FAIL_TRANSITION, # "a - b" (or similar) would never be a valid start to a statement
        FAIL_TRANSITION, # "a .. b" (or similar) would never be a valid start to a statement
        ('statement_read_lvalue_hopefully_:', 'stay', 'read', None),
        check_if_function_call=True)
    # Note that we can also reach 'statement_read_lvalue_hopefully' if
    # the first thing that was read was a '('. See the "Statements that
    # start with a name" section for more.

    # First, check for what we'd expect if this was an assignment statement...
    transitions[('statement_read_lvalue_hopefully', b',', 'lvalue_or_rvalue')] = ('statement_read_lvalue', 'stay', 'pop', None)
    transitions[('statement_read_lvalue_hopefully', b'=', 'lvalue_or_rvalue')] = ('statement_read_lvalue', 'stay', 'pop', None)
    transitions[('statement_read_lvalue', b',', None)] = ('statement_assign_varlist', 'right', 'pop', None)
    transitions[('statement_read_lvalue', b'=', None)] = ('statement_assign_rightside', 'right', 'pop', None)

    # Or maybe this is a function call?
    # If so, the statement is entirely finished at this point, so just
    # go all the way back to the 'statement' state.
    for c in ALL:
        transitions[('statement_read_lvalue_hopefully', c, 'rvalue')] = ('statement_function_call_maybe', 'stay', 'pop', None)
        transitions[('statement_function_call_maybe', c, 'function_call')] = ('statement', 'stay', 'pop', None)

    # If the lrvalue ended with a "::", this has to be a function call
    # followed by a label (which we already consumed a portion of)
    transitions[('statement_read_lvalue_hopefully_:', b':', 'rvalue')] = ('statement_function_call_maybe_:', 'stay', 'pop', None)
    transitions[('statement_function_call_maybe_:', b':', 'function_call')] = ('statement_dbcolon_:', 'stay', 'pop', None)

    # -------- Assignment statements --------

    # Read any more lvalues (separated by commas)
    for c in ALL:
        transitions[('statement_assign_varlist', c, None)] = ('statement_assign_varlist_2', 'stay', 'read', None)
    read_whitespace('statement_assign_varlist', FAIL_TRANSITION)
    read_lvalue_or_rvalue('statement_assign_varlist_2', False,
        ('statement_assign_read_another_lvalue_hopefully', 'stay', 'read', None),
        FAIL_TRANSITION, FAIL_TRANSITION, FAIL_TRANSITION)
    transitions[('statement_assign_read_another_lvalue_hopefully', b',', 'lvalue_or_rvalue')] = ('statement_assign_varlist', 'right', 'pop', None)
    transitions[('statement_assign_read_another_lvalue_hopefully', b'=', 'lvalue_or_rvalue')] = ('statement_assign_rightside', 'right', 'pop', None)

    # Handle the right side
    # (Note: we can also end up in the statement_assign_rightside state
    # through a local-assignment statement (defined elsewhere))
    read_expression_list('statement_assign_rightside',
        ('statement', 'stay', 'read', None),
        trailing_name_transition=('statement_starting_with_name', 'stay', 'read', None),
        colon_transition=('statement_dbcolon_:', 'stay', 'read', None))

    # ======== Statements that start with a keyword ========

    # Make transitions from statement_starting_with_keyword to more specific states
    for c in NOT_LISLALNUM:
        # case TK_IF: {  /* stat -> ifstat */
        transitions[('statement_starting_with_keyword', c, 'if')] = ('statement_if', 'stay', 'replace', 'statement_if')
        transitions[('statement_starting_with_keyword', c, 'elseif')] = ('statement_elseif', 'stay', 'pop', None)
        transitions[('statement_starting_with_keyword', c, 'else')] = ('statement_else', 'stay', 'pop', None)
        # case TK_WHILE: {  /* stat -> whilestat */
        transitions[('statement_starting_with_keyword', c, 'while')] = ('statement_while', 'stay', 'replace', 'statement_while')
        # case TK_DO: {  /* stat -> DO block END */
        transitions[('statement_starting_with_keyword', c, 'do')] = ('statement', 'stay', 'replace', 'statement_do')
        # case TK_FOR: {  /* stat -> forstat */
        transitions[('statement_starting_with_keyword', c, 'for')] = ('statement_for', 'stay', 'replace', 'statement_for')
        # case TK_REPEAT: {  /* stat -> repeatstat */
        transitions[('statement_starting_with_keyword', c, 'repeat')] = ('statement', 'stay', 'replace', 'statement_repeat')
        transitions[('statement_starting_with_keyword', c, 'until')] = ('statement_until', 'stay', 'pop', None)
        # case TK_FUNCTION: {  /* stat -> funcstat */
        transitions[('statement_starting_with_keyword', c, 'function')] = ('statement_function', 'stay', 'replace', 'statement_function')
        # case TK_LOCAL: {  /* stat -> localstat */
        transitions[('statement_starting_with_keyword', c, 'local')] = ('statement_local', 'stay', 'pop', None)
        # case TK_RETURN: {  /* stat -> retstat */
        transitions[('statement_starting_with_keyword', c, 'return')] = ('statement_return', 'stay', 'pop', None)
        # case TK_BREAK: {  /* stat -> breakstat */
        transitions[('statement_starting_with_keyword', c, 'break')] = ('statement', 'stay', 'pop', None)
        # case TK_GOTO: {  /* stat -> 'goto' NAME */
        transitions[('statement_starting_with_keyword', c, 'goto')] = ('statement_goto', 'stay', 'pop', None)

    # ---- If statements ----
    # (starts on 'statement_if' state with 'statement_if' on top of stack)
    # Read expression (including leading/trailing whitespace)
    read_expression('statement_if', ('statement_if_after_expression', 'stay', 'read', None))
    # Read "then", and then transition to statement
    transitions[('statement_if_after_expression', b't', None)] = ('statement_if_after_expression_t', 'right', 'read', None)
    transitions[('statement_if_after_expression_t', b'h', None)] = ('statement_if_after_expression_th', 'right', 'read', None)
    transitions[('statement_if_after_expression_th', b'e', None)] = ('statement_if_after_expression_the', 'right', 'read', None)
    transitions[('statement_if_after_expression_the', b'n', None)] = ('statement', 'right', 'read', None)

    # If we read an "elseif" while "statement_if" is on top of the stack, handle it like an "if"
    read_expression('statement_elseif', ('statement_if_after_expression', 'stay', 'read', None), required_stack_value='statement_if')

    # If we read an "else" while "statement_if" is on top of the stack, go back to the "statement" state
    for c in ALL:
        transitions[('statement_else', c, 'statement_if')] = ('statement', 'stay', 'read', None)


    # ---- While statements ----
    # (starts on 'statement_while' state with 'statement_while' on top of stack)
    # Read expression (including leading/trailing whitespace)
    read_expression('statement_while', ('statement_while_after_expression', 'stay', 'read', None))
    # Read "do", and then transition to statement
    transitions[('statement_while_after_expression', b'd', None)] = ('statement_while_after_expression_d', 'right', 'read', None)
    transitions[('statement_while_after_expression_d', b'o', None)] = ('statement', 'right', 'read', None)

    # ---- Do statements ----
    # (starts in "statement" state, with "statement_do" on the stack)
    # (Nothing to do here; this is entirely handled by "end")

    # ---- For statements ----
    # (starts on 'statement_for' state with 'statement_for' on top of stack)
    # Read whitespace after the "for" keyword
    read_whitespace('statement_for', FAIL_TRANSITION)
    # Read name and then more whitespace
    read_name_or_keyword('statement_for', ('statement_for_name', 'stay', 'read', None), FAIL_TRANSITION)
    read_whitespace('statement_for_name', FAIL_TRANSITION)

    # Numerical for-loop: "stat ::= for Name ‘=’ exp ‘,’ exp [‘,’ exp] do block end"
    transitions[('statement_for_name', b'=', None)] = ('statement_numfor_=', 'right', 'read', None)
    read_expression('statement_numfor_=', ('statement_numfor_=_exp', 'stay', 'read', None))
    transitions[('statement_numfor_=_exp', b',', None)] = ('statement_numfor_=_exp_,', 'right', 'read', None)
    read_expression('statement_numfor_=_exp_,', ('statement_numfor_=_exp_,_exp', 'stay', 'read', None))
    transitions[('statement_numfor_=_exp_,_exp', b'd', None)] = ('statement_numfor_=_exp_,_exp_,_exp_d', 'right', 'read', None)
    transitions[('statement_numfor_=_exp_,_exp', b',', None)] = ('statement_numfor_=_exp_,_exp_,', 'right', 'read', None)
    read_expression('statement_numfor_=_exp_,_exp_,', ('statement_numfor_=_exp_,_exp_,_exp', 'stay', 'read', None))
    transitions[('statement_numfor_=_exp_,_exp_,_exp', b'd', None)] = ('statement_numfor_=_exp_,_exp_,_exp_d', 'right', 'read', None)
    transitions[('statement_numfor_=_exp_,_exp_,_exp_d', b'o', None)] = ('statement', 'right', 'read', None)

    # Generic for-loop: "stat ::= for namelist in explist do block end"
    transitions[('statement_for_name', b',', None)] = ('statement_genfor_namelist_,', 'right', 'read', None)
    transitions[('statement_for_name', b'i', None)] = ('statement_genfor_namelist_i', 'right', 'read', None)
    for c in ALL:
        transitions[('statement_genfor_namelist_,', c, None)] = ('statement_genfor_namelist_,_whitespace', 'stay', 'read', None)
    read_whitespace('statement_genfor_namelist_,', FAIL_TRANSITION)
    read_name_list('statement_genfor_namelist_,_whitespace',
        ('statement_genfor_namelist', 'stay', 'read', None),
        FAIL_TRANSITION)
    transitions[('statement_genfor_namelist', b'i', None)] = ('statement_genfor_namelist_i', 'right', 'read', None)
    transitions[('statement_genfor_namelist_i', b'n', None)] = ('statement_genfor_namelist_in', 'right', 'read', None)
    read_expression_list('statement_genfor_namelist_in',
        ('statement_genfor_namelist_in_explist', 'stay', 'read', None))
    transitions[('statement_genfor_namelist_in_explist', b'd', None)] = ('statement_genfor_namelist_in_explist_d', 'right', 'read', None)
    transitions[('statement_genfor_namelist_in_explist_d', b'o', None)] = ('statement', 'right', 'read', None)

    # ---- Repeat statements ----
    # (starts on 'statement' state with 'statement_repeat' on top of stack)
    # (Nothing to do for that first part.)

    # If we read an "until" while "statement_repeat" is on top of the stack,
    # read the expression that follows, and pop the "statement_repeat" off the stack
    read_expression('statement_until',
        ('statement', 'stay', 'pop', None),
        trailing_name_transition=('statement_starting_with_name', 'stay', 'pop', None),
        colon_transition=('statement_dbcolon_:', 'stay', 'pop', None),
        required_stack_value='statement_repeat')

    # ---- Function statements ----
    # (starts in "statement_function" state, with "statement_function" on the stack)

    # Read whitespace after the "function" keyword
    read_whitespace('statement_function', FAIL_TRANSITION)

    # Syntax for a function name is name{.name}[:name]
    # (i.e. a name, followed by 0 or more .name, followed by one optional :name)
    # Whitespace, including comments, can appear between any of those tokens.

    # Start as if we just read a "."
    for c in IN_LISLALNUM:
        transitions[('statement_function', c, None)] = ('func_name_.', 'stay', 'read', None)

    # Read whitespace and then another name
    read_whitespace('func_name_.', FAIL_TRANSITION)
    read_name_or_keyword('func_name_.', ('func_name', 'stay', 'read', None), FAIL_TRANSITION)

    # Possibly read whitespace before the "." or ":"
    read_whitespace('func_name', FAIL_TRANSITION)

    # Maybe read another "." and loop back up
    transitions[('func_name', b'.', None)] = ('func_name_.', 'right', 'read', None)

    # Or read a ":" followed by whitespace, one more name, and more whitespace
    transitions[('func_name', b':', None)] = ('func_name_:', 'right', 'read', None)
    read_whitespace('func_name_:', FAIL_TRANSITION)
    read_name_or_keyword('func_name_:', ('func_name_:name', 'stay', 'read', None), FAIL_TRANSITION)
    read_whitespace('func_name_:name', FAIL_TRANSITION)

    # Go to the func_body_start state once we hit the opening '('
    transitions[('func_name', b'(', None)] = ('func_body_start', 'stay', 'read', None)
    transitions[('func_name_:name', b'(', None)] = ('func_body_start', 'stay', 'read', None)

    # Transition back, checking for 'statement_function' being on the stack
    for c in ALL:
        transitions[('func_body_end', c, 'statement_function')] = ('statement', 'stay', 'pop', None)

    # ---- Local statements ----
    # (starts on 'statement_local' state with nothing on top of stack)
    #     stat ::= local function Name funcbody
    #     OR
    #     stat ::= local namelist [‘=’ explist]

    # Read whitespace after the "local" keyword
    for c in ALL:
        transitions[('statement_local', c, None)] = ('statement_local_after_whitespace', 'stay', 'read', None)
    read_whitespace('statement_local', FAIL_TRANSITION)

    read_name_list('statement_local_after_whitespace',
        ('statement_local_after_name_list', 'stay', 'read', None),
        ('statement_local_read_keyword', 'stay', 'read', None))

    # If we got an actual name list, try to read an '=' and merge into
    # the system for reading regular assignment expressions
    transitions[('statement_local_after_name_list', b'=', None)] = ('statement_assign_rightside', 'right', 'read', None)
    # If we got an actual name list but there's no '=', this must be
    # just a "local x, y, z" statement. Try to read whatever follows as
    # a statement
    for c in u8_complement(b'='):
        transitions[('statement_local_after_name_list', c, None)] = ('statement', 'stay', 'read', None)

    # If we got a keyword, ensure that it was 'function', and then read
    # the rest of it
    for c in ALL:
        transitions[('statement_local_read_keyword', c, 'function')] = ('statement_local_function', 'stay', 'pop', None)
    read_whitespace('statement_local_function', FAIL_TRANSITION)
    read_name_or_keyword('statement_local_function',
        ('statement_local_function_read_name', 'stay', 'read', None),
        FAIL_TRANSITION)
    read_whitespace('statement_local_function_read_name', FAIL_TRANSITION)
    transitions[('statement_local_function_read_name', b'(', None)] = ('func_body_start', 'stay', 'push', 'statement_local_function')
    for c in ALL:
        transitions[('func_body_end', c, 'statement_local_function')] = ('statement', 'stay', 'pop', None)

    # ---- Return statements ----
    # (starts on 'statement_return' state with nothing on top of stack)
    #     retstat ::= return [explist] [‘;’]
    # The thing about return statements in Lua is that they're
    # syntactically required to be at the end of a block (that is,
    # they're followed by one of the following: "end", "elseif", "else",
    # "until", or EOF).
    # (Also note that the production for retstat allows an optional
    # semicolon, too.)
    # We will parse it in a way that enforces all that.

    # Read expression (including leading/trailing whitespace)
    read_expression_list('statement_return',
        ('statement_return_after_expression', 'stay', 'read', None),   # (read an actual expression)
        ('statement_return_end', 'stay', 'read', None),                # (read an "end")
        ('statement_return_elseif', 'stay', 'read', None),             # (read an "elseif")
        ('statement_return_else', 'stay', 'read', None),               # (read an "else")
        ('statement_return_until', 'stay', 'read', None),              # (read an "until")
        ('statement_return_after_expression_;', 'stay', 'read', None)) # (read a ";")

    # Read optional ';', followed by 'end', 'else', 'elseif', or 'until'
    # (and ensure that each keyword is followed by non-alphanumeric characters)
    read_whitespace('statement_return_after_expression', FAIL_TRANSITION)
    transitions[('statement_return_after_expression', b';', None)] = ('statement_return_after_expression_;', 'right', 'read', None)
    read_whitespace('statement_return_after_expression_;', FAIL_TRANSITION)
    transitions[('statement_return_after_expression', b'e', None)] = ('statement_return_after_expression_;e', 'right', 'read', None)
    transitions[('statement_return_after_expression_;', b'e', None)] = ('statement_return_after_expression_;e', 'right', 'read', None)
    transitions[('statement_return_after_expression_;e', b'l', None)] = ('statement_return_after_expression_;el', 'right', 'read', None)
    transitions[('statement_return_after_expression_;el', b's', None)] = ('statement_return_after_expression_;els', 'right', 'read', None)
    transitions[('statement_return_after_expression_;els', b'e', None)] = ('statement_return_after_expression_;else', 'right', 'read', None)
    for c in NOT_LISLALNUM:
        transitions[('statement_return_after_expression_;else', c, None)] = ('statement_return_else', 'stay', 'read', None)
    transitions[('statement_return_after_expression_;else', b'i', None)] = ('statement_return_after_expression_;elsei', 'right', 'read', None)
    transitions[('statement_return_after_expression_;elsei', b'f', None)] = ('statement_return_after_expression_;elseif', 'right', 'read', None)
    for c in NOT_LISLALNUM:
        transitions[('statement_return_after_expression_;elseif', c, None)] = ('statement_return_elseif', 'stay', 'read', None)
    transitions[('statement_return_after_expression_;e', b'n', None)] = ('statement_return_after_expression_;en', 'right', 'read', None)
    transitions[('statement_return_after_expression_;en', b'd', None)] = ('statement_return_after_expression_;end', 'right', 'read', None)
    for c in NOT_LISLALNUM:
        transitions[('statement_return_after_expression_;end', c, None)] = ('statement_return_end', 'stay', 'read', None)
    transitions[('statement_return_after_expression', b'u', None)] = ('statement_return_after_expression_;u', 'right', 'read', None)
    transitions[('statement_return_after_expression_;', b'u', None)] = ('statement_return_after_expression_;u', 'right', 'read', None)
    transitions[('statement_return_after_expression_;u', b'n', None)] = ('statement_return_after_expression_;un', 'right', 'read', None)
    transitions[('statement_return_after_expression_;un', b't', None)] = ('statement_return_after_expression_;unt', 'right', 'read', None)
    transitions[('statement_return_after_expression_;unt', b'i', None)] = ('statement_return_after_expression_;unti', 'right', 'read', None)
    transitions[('statement_return_after_expression_;unti', b'l', None)] = ('statement_return_after_expression_;until', 'right', 'read', None)
    for c in NOT_LISLALNUM:
        transitions[('statement_return_after_expression_;until', c, None)] = ('statement_return_until', 'stay', 'read', None)

    # At this point, we should be in one of the following states:
    # - statement_return_else
    # - statement_return_elseif
    # - statement_return_end
    # - statement_return_until

    # Return from "else", "elseif", or "until"
    for c in NOT_LISLALNUM:
        transitions[('statement_return_else', c, 'statement_if')] = ('statement_else', 'stay', 'read', None)
        transitions[('statement_return_elseif', c, 'statement_if')] = ('statement_elseif', 'stay', 'read', None)
        transitions[('statement_return_until', c, 'statement_repeat')] = ('statement_until', 'stay', 'read', None)

    # Return from "end"
    # (Ensure that we'll be ending an appropriate block)
    for required_stack_value, dest in STACK_VALUES_POPPED_BY_END_KEYWORD.items():
        for c in NOT_LISLALNUM:
            transitions[('statement_return_end', c, required_stack_value)] = (dest, 'stay', 'pop', None)

    # ---- Break statements ----
    # (starts in "statement" state, with nothing on the stack)
    # (Nothing to do here at all)

    # ---- Goto statements ----
    # (starts in "statement_goto" state, with nothing on the stack)
    read_whitespace('statement_goto', FAIL_TRANSITION)
    read_name_or_keyword('statement_goto', ('statement', 'stay', 'read', None), FAIL_TRANSITION)


    # ======== "end" keyword ========
    # First, we have to pop the "end" off the stack
    for c in NOT_LISLALNUM:
        transitions[('statement_starting_with_keyword', c, 'end')] = ('statement_end', 'stay', 'pop', None)
    # Then we pop again to get rid of the "statement_do" or "statement_if" or whatever
    for required_stack_value, dest in STACK_VALUES_POPPED_BY_END_KEYWORD.items():
        for c in NOT_LISLALNUM:
            transitions[('statement_end', c, required_stack_value)] = (dest, 'stay', 'pop', None)


    ####################################################################
    ####################################################################
    ######################## Start (Entrypoint) ########################
    ####################################################################
    ####################################################################

    # "The first line in the file is ignored if it starts with a #."
    for c in ALL:
        transitions[('start', c, None)] = ('statement', 'stay', 'read', None)
    transitions[('start', b'#', None)] = ('start_#', 'right', 'read', None)
    for c in ALL:
        transitions[('start_#', c, None)] = ('start_#', 'right', 'read', None)
    for c in bstr_to_set(b'\r\n'):
        transitions[('start_#', c, None)] = ('statement', 'right', 'read', None)


    ####################################################################
    ####################################################################
    ############################### (End) ##############################
    ####################################################################
    ####################################################################

    return transitions


class Lua_2PDA(pda.TwoPDA):
    """
    2PDA for Lua 5.3
    """
    name = 'Lua'
    transitions = _make_transitions()
    initial_state = 'start'


# For the curious
Lua_2PDA.print_stats()
