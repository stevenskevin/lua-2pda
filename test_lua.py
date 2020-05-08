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

import pathlib

import pytest

import pda_lua


DEBUG_LEVEL = 0
COUNTER = 0

def reset_counter():
    pass
    global COUNTER
    COUNTER = 0

def end():
    pass
    raise Exception('Intentional test failure')

def parse_lua(s, *args, **kwargs):
    """
    Helper function that parses something with the appropriate debug_level set
    """
    global COUNTER
    COUNTER += 1
    print(COUNTER)
    if isinstance(s, str):
        s = s.encode('cp1252')
    pda_lua.Lua_2PDA().parse(s, *args, **kwargs, debug_level=DEBUG_LEVEL)


def iter_whitespace():
    """
    Helper function to iterate over various whitespace.
    Yields: ws, ws_sep
    Where ws is whitespace (possibly empty) and ws_sep is the same as
    ws, unless ws is empty, in which case it will be one space.
    """
    def make_both(ws):
        return ws, (ws if ws else ' ')
    yield make_both('')
    yield make_both(' ')
    yield make_both('--\n')
    yield make_both(' --\n ')
    yield make_both('--[[comment]]')
    yield make_both(' --[[comment]] ')


# Add tests corresponding to files in the Lua test suite.
# You can have these be skipped by running `pytest -m "not luasuite"`
def make_test_suite_test(path):
    """
    Factory function for creating a test case that parses a Lua file at
    the given path (pathlib.Path) and runs it through the 2PDA
    """
    @pytest.mark.luasuite
    def test():
        parse_lua(path.read_bytes())

    return test

for p in pathlib.Path('lua-5.3/testes/').glob('*.lua'):
    globals()[f'test_lua_test_suite_{p.stem}'] = make_test_suite_test(p)

del make_test_suite_test


def helper_test_multiline_comment_or_long_string(prefix):
    """
    Helper function to test parsing multiline comments or long strings.
    
    prefix should be a string that will be prefixed onto all test cases.
    """

    def check_closed(equals):
        """
        Perform a check to see if an --[equals[ multiline comment or
        [equals[ long-form string has been closed as it should have been

        We do this by adding a comment of the form
        --[other[ ]equals] ]other]
        (where "other" is some other amount of equals)

        If --[equals[ had been properly closed, this is a perfectly
        valid comment. If not, it closes the original comment or string
        and leaves some unparseable "]other]" garbage afterwards,
        causing a syntax error
        """
        other = '==' if equals == '====' else '===='
        return f'  --[{other}[ ]{equals}] ]{other}]'

    parse_lua(prefix + '[[multiline\rcomment\n]not yet]]' + check_closed(''))
    parse_lua(prefix + '[====[multiline\rcomment\n]=not yet]====]' + check_closed('===='))
    parse_lua(prefix + '[====[multiline\rcomment\n]]====]' + check_closed('===='))
    parse_lua(prefix + '[[]]' + check_closed(''))
    parse_lua(prefix + '[=[]=]' + check_closed('='))

    # 10 opening '='s, 11 ending ones -- should be counted as equal with
    # the current PDA implementation
    parse_lua(prefix + '[==========[multiline\rcomment\n]]===========]' + check_closed('=========='))

    # Non-ASCII characters
    parse_lua((prefix + '[=[ ツ ]]=]' + check_closed('=')).encode('utf-8'))

    # Some things that should *not* parse
    with pytest.raises(Exception):
        parse_lua(prefix + '[[multiline\rcomment\n]=]' + check_closed(''))
    with pytest.raises(Exception):
        parse_lua(prefix + '[=[multiline\rcomment\n]]' + check_closed('='))
    with pytest.raises(Exception):
        parse_lua(prefix + '[=[multiline\rcomment\n]==]' + check_closed('='))
    with pytest.raises(Exception):
        parse_lua(prefix + '[=[multiline\rcomment\n]]]' + check_closed('='))
    with pytest.raises(Exception):
        parse_lua(prefix + '[=[multiline\rcomment\n]]==]' + check_closed('='))


def helper_test_function_bodies(prefix):
    """
    Helper function to test parsing function statements or function
    expressions.
    
    prefix should be a string that will be prefixed onto all test cases.
    """
    for ws, ws_sep in iter_whitespace():
        parse_lua(prefix + '( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(prefix + '( a ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(prefix + '( ... ) do ; ::x::end; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(prefix + '( a , b , ... ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(prefix + '( a , bb , ccc , ... ) end ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua(prefix + '( .. )_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(prefix + '( a , )_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(prefix + '( , a )_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(prefix + '( a_b ) end_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(prefix + '( a ... ) end_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(prefix + '( a , ... , c )_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(prefix + '( ) end_end_'.replace(' ', ws).replace('_', ws_sep))


def test_bang():
    """
    Test that "The first line in the file is ignored if it starts with a #."
    """
    reset_counter()
    # Single-line
    parse_lua('#shebang line\ndo --\n end')
    with pytest.raises(Exception):
        parse_lua('#shebang line\noh no invalid syntax')
    end()


def test_comment():
    """
    Test parsing comments
    """
    reset_counter()
    # Single-line
    parse_lua(' --this is a comment\ndo end')
    parse_lua('do --\n end')
    with pytest.raises(Exception):
        parse_lua(' --this is a comment\noops the comment ended')

    helper_test_multiline_comment_or_long_string('--')

    # A parsing error when trying to read the start of a multiline
    # comment should cause it to read the rest of the line as a
    # single-line comment instead
    parse_lua('do --[\n end')
    parse_lua('do --[=\n end')
    parse_lua('do --[==\n end')
    end()



def test_name():
    """
    Test name parsing
    """
    reset_counter()

    parse_lua('a = 1;')
    parse_lua('abc123 = 1;')
    parse_lua('_abc_123_ = 1;')

    with pytest.raises(Exception):
        parse_lua('123abc = 1;')
    end()


def test_semicolon():
    """
    Test the semicolon statement
    """
    reset_counter()
    parse_lua(';')
    parse_lua('; ;;; ; ;; ; ;;;;;;;   ; ;; ')
    end()


def test_assignment_statement():
    """
    Test assignment statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        for exp in ['nil', '1', '-23', 'd', 'a.b(c)[d]']: # important to check that negative numbers work
            parse_lua(f'a = {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua(f'a . b = {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua(f'a , bb . cc = {exp} , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua(f'a , bb , ccc . ddd = {exp} , {exp} , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))

            with pytest.raises(Exception):
                parse_lua(f'a {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua(f'a , b {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua(f'a , if = {exp} , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('a , b = if ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('a , b , c ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('a , b , c , ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('a , b , c = ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_function_call_statement():
    """
    Test parsing function-call statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():

        # ======== Var ========
        parse_lua('a = 1 ;_'.replace(' ', ws).replace('_', ws_sep))                       # (none)
        parse_lua('a [ -23 ] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))               # [exp]
        parse_lua('a . b = 1 ;_'.replace(' ', ws).replace('_', ws_sep))                   # .name
        parse_lua('( a ) . c = 1 ;_'.replace(' ', ws).replace('_', ws_sep))               # starting with (
        with pytest.raises(Exception):
            parse_lua('a : b = 1 ;_'.replace(' ', ws).replace('_', ws_sep))               # :name, with no args
        with pytest.raises(Exception):
            parse_lua('a : b ( 1 , 2 ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))     # :name (args)
        with pytest.raises(Exception):
            parse_lua("a : b 'arg' = 1 ;_".replace(' ', ws).replace('_', ws_sep))         # :name 'string argument'
        with pytest.raises(Exception):
            parse_lua('a : b "arg" = 1 ;_'.replace(' ', ws).replace('_', ws_sep))         # :name "string argument"
        with pytest.raises(Exception):
            parse_lua('a : b [[arg]] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))       # :name [[string argument]]
        with pytest.raises(Exception):
            parse_lua('a : b [==[arg]==] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))   # :name [==[string argument]==]
        with pytest.raises(Exception):
            parse_lua('a : b { 1 , 2 ; 3 } = 1 ;_'.replace(' ', ws).replace('_', ws_sep)) # :name {table constructor argument}
        with pytest.raises(Exception):
            parse_lua('a ( 1 , 2 ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))         # (args)
        with pytest.raises(Exception):
            parse_lua("a 'arg' = 1 ;_".replace(' ', ws).replace('_', ws_sep))             # 'string argument'
        with pytest.raises(Exception):
            parse_lua('a "arg" = 1 ;_'.replace(' ', ws).replace('_', ws_sep))             # "string argument"
        with pytest.raises(Exception):
            parse_lua('a [[ arg ]] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))         # [[string argument]]
        with pytest.raises(Exception):
            parse_lua('a [==[arg]==] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))       # [==[string argument]==]
        with pytest.raises(Exception):
            parse_lua('a { 1 , 2 ; 3 } = 1 ;_'.replace(' ', ws).replace('_', ws_sep))     # {table constructor argument}
        with pytest.raises(Exception):
            parse_lua('( a ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))               # starting with (, with nothing following

        # Test chaining multiple parts

        parse_lua('a ( b ) . c [ e ] "f" [[g]] [ h . i ] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a ( b ) . c [ e ] "f" [[g]] [ h . i ] ( ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))

        parse_lua('a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) . j = 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) "j" = 1 ;_'.replace(' ', ws).replace('_', ws_sep))

        # ======== Prefixexp ========
        for exp in ['nil', '1', '-23']: # important to check that negative numbers work
            parse_lua( 'a = a ;_'.replace(' ', ws).replace('_', ws_sep))                                 # (none)
            parse_lua(f'a = a [ {exp} ] ;_'.replace(' ', ws).replace('_', ws_sep))                       # [exp]
            parse_lua( 'a = a . b ;_'.replace(' ', ws).replace('_', ws_sep))                             # .name
            parse_lua(f'a = a : b ( {exp} , {exp} ) ;_'.replace(' ', ws).replace('_', ws_sep))           # :name (args)
            parse_lua( "a = a : b 'arg' ;_".replace(' ', ws).replace('_', ws_sep))                       # :name 'string argument'
            parse_lua( 'a = a : b "arg" ;_'.replace(' ', ws).replace('_', ws_sep))                       # :name "string argument"
            parse_lua( 'a = a : b [[arg]] ;_'.replace(' ', ws).replace('_', ws_sep))                     # :name [[string argument]]
            parse_lua( 'a = a : b [==[arg]==] ;_'.replace(' ', ws).replace('_', ws_sep))                 # :name [==[string argument]==]
            parse_lua(f'a = a : b {{ {exp} , {exp} ; {exp} }} ;_'.replace(' ', ws).replace('_', ws_sep)) # :name {table constructor argument}
            parse_lua(f'a = a ( {exp} , {exp} ) ;_'.replace(' ', ws).replace('_', ws_sep))               # (args)
            parse_lua( "a = a 'arg' ;_".replace(' ', ws).replace('_', ws_sep))                           # 'string argument'
            parse_lua( 'a = a "arg" ;_'.replace(' ', ws).replace('_', ws_sep))                           # "string argument"
            parse_lua( 'a = a [[arg]] ;_'.replace(' ', ws).replace('_', ws_sep))                         # [[string argument]]
            parse_lua( 'a = a [==[arg]==] ;_'.replace(' ', ws).replace('_', ws_sep))                     # [==[string argument]==]
            parse_lua(f'a = a {{ {exp} , {exp} ; {exp} }} ;_'.replace(' ', ws).replace('_', ws_sep))     # {table constructor argument}
            parse_lua( 'a = ( a ) ;_'.replace(' ', ws).replace('_', ws_sep))                             # starting with (
            parse_lua( 'a = ( a ) . b ;_'.replace(' ', ws).replace('_', ws_sep))                         # starting with (, with something else following
        with pytest.raises(Exception):
            parse_lua( 'a = a : b ;_'.replace(' ', ws).replace('_', ws_sep))                             # :name, with no args
        with pytest.raises(Exception):
            parse_lua( 'a = ( a , b ) ;_'.replace(' ', ws).replace('_', ws_sep))                         # this should not be read as a function call

        # Test chaining multiple parts

        parse_lua('a = a ( b ) . c [ e ] "f" [[g]] [ h . i ] ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = a ( b ) . c [ e ] "f" [[g]] [ h . i ] : j ;_'.replace(' ', ws).replace('_', ws_sep))

        parse_lua('a = a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) . j ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) : j ;_'.replace(' ', ws).replace('_', ws_sep))

    end()


def test_label_statement():
    """
    Test the label statement
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua(':: x :: ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(';; :: abcdefg :: ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('do ;; :: abcdefg :: ;; end ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua(':: :: ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(':: 33 :: ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(':: if :: ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(':: x : ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(': x :: ;_'.replace(' ', ws).replace('_', ws_sep))

        # Test labels following all kinds of expressions where it could
        # be mistaken for the start of a "a:b()" function call, including...
        # ...assignment statement:
        parse_lua('a = b :: label :: ;_'.replace(' ', ws).replace('_', ws_sep))
        # ...local assignment statement:
        parse_lua('local a = b :: label :: ;_'.replace(' ', ws).replace('_', ws_sep))
        # ...function call statement:
        parse_lua('b ( ) :: label :: ;_'.replace(' ', ws).replace('_', ws_sep))
        # ...repeat-until loop statement:
        parse_lua('repeat ; until_a :: label :: ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_break_statement():
    """
    Test parsing the break statement
    """
    reset_counter()
    parse_lua('break')

    for ws, ws_sep in iter_whitespace():
        parse_lua('do break end'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_goto_statement():
    """
    Test parsing goto statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('goto_x ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('goto_xyz ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('goto_5 ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('goto ( x ) ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_do_statement():
    """
    Test parsing do-end blocks
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('do end'.replace(' ', ws_sep))
        parse_lua('do do end end'.replace(' ', ws_sep))
        parse_lua('do end do end'.replace(' ', ws_sep))
        parse_lua('do ;; ;; do ;; end ; end ;;;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('do_end_end ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_while_statement():
    """
    Test parsing while statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('while_nil_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('while_true_do ; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('while_-23_do ;;; do_end_end_do_end ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('while_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('while_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('while ; do ; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('while_true_then_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('while_..._do_else_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('while_nil_do_end_end ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_repeat_statement():
    """
    Test parsing repeat statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('repeat_until_-23 ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('repeat ;;; do_end_until_..._do_end ;_'.replace(' ', ws).replace('_', ws_sep))
        # Test that it handles the "expression parser tries to read 'and' but fails" case
        parse_lua('repeat_until_5_andz ( nil , nil ) do_end ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('repeat_nil ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('repeat_until_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('repeat ; until ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('repeat_then ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('repeat_else_until ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('repeat ; until_false_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('repeat ; until_nil_until_nil ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_if_statement():
    """
    Test parsing if statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('if_true_then_end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('if_..._then_elseif_true_then_else_end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('if_-23_then ; elseif_true_then ; else_end ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('if_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('if_then_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('if_nil_then_elseif_then_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('if_nil ; then_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('if_nil_then_elseif_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('else ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('elseif ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('if_nil_then_end_end ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_numerical_for_loop_statement():
    """
    Test parsing "numerical" for-loop statements, i.e.
    stat ::= for Name ‘=’ exp ‘,’ exp [‘,’ exp] do block end
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('for_a = b , c_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('for_a = b , c , d_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('for_a = -1 , -2 , -3_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('for_a = b do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('for_a = b , c , d , e_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('for_true = b_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('for_a, b = b_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('for_a = b_do ;;; end_end ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_generic_for_loop_statement():
    """
    Test parsing "generic" for-loop statements, i.e.
    stat ::= for namelist in explist do block end
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('for_a_in_b_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('for_a , b , c_in_d , e , f_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('for_a_in_nil , -23 , true , b . c [ e ] { f } "g" ( h ) do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('for_a_in_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('for_in_b_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('for_true_in_b_do ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('for_a_in_b_do ;;; end_end ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_function_statement():
    """
    Test parsing function statements
    """
    reset_counter()
    helper_test_function_bodies('function x.y.z:a')

    for ws, ws_sep in iter_whitespace():

        # Test various combinations of .'s and :'s
        parse_lua('function_x ( ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('function_x . y ( ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('function_x : y ( ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('function_x . y . z ( ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('function_x . y : z ( ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('function_x . y . z : a ( ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))

        # Test functions with multi-character names
        parse_lua('function xyz123abc(a) ;;; end ')

        # Test functions with invalid names
        with pytest.raises(Exception):
            parse_lua('function () end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('function_nil ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('function_end ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('function_3 ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('function_a : b : c ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_local_function_statement():
    """
    Test parsing local-function statements
    """
    reset_counter()
    helper_test_function_bodies('local function x')

    for ws, ws_sep in iter_whitespace():

        # Basic test
        parse_lua('local_function_xyz123abc ( a ) ;;; end ;_'.replace(' ', ws).replace('_', ws_sep))

        # Test local functions with invalid names
        with pytest.raises(Exception):
            parse_lua('local_function ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('local_function_nil ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('local_function_end ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('local_function_3 ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('local_function_a . b ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('local_function_a : b ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('local_function_a_b ( ) end ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_local_assignment_statement():
    """
    Test parsing local-assignment statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        for exp in ['nil', '1', '-23', 'a.b(c)[d]']: # important to check that negative numbers work
            parse_lua(f'local_a ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua(f'local_a ; local_b ; local_c ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua(f'local_a_local_b_local_c ;_'.replace(' ', ws).replace('_', ws_sep))

            parse_lua(f'local_a = {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua(f'local_a , bb = {exp} , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua(f'local_a , bb , ccc = {exp} , {exp} , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))

            with pytest.raises(Exception):
                parse_lua(f'local_a_{exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua(f'local_a , b_{exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua(f'local_a , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua(f'local_a , b , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua(f'local_a , if = {exp} , {exp} ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('local_a , b = if ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('local_a , b , c , ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('local_a , b , c = ;_'.replace(' ', ws).replace('_', ws_sep))
            with pytest.raises(Exception):
                parse_lua('local_a_b = ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_return_statement():
    """
    Test parsing return statements
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        for semicolon in ['_', ';']:
            for explist in ['_', '_nil_', '_nil , nil_', '_nil , nil , nil_', '_-23_']:
                parse_lua(f'return {explist} {semicolon}'.replace(' ', ws).replace('_', ws_sep))
                parse_lua(f'function_x ( ) return {explist} {semicolon} end_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
                parse_lua(f'do_return {explist} {semicolon} end_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
                parse_lua(f'if_nil_then_return {explist} {semicolon} else_do_end_end ;_'.replace(' ', ws).replace('_', ws_sep))
                parse_lua(f'if_nil_then_return {explist} {semicolon} elseif_nil_then_do_end_end ;_'.replace(' ', ws).replace('_', ws_sep))
                parse_lua(f'repeat_return {explist} {semicolon} until_nil ;_'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('function_x ( ) return_nil , end_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('function_x ( ) return_nil , ; end_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('function_x ( ) return , ; end_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('return , ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('function_x ( ) return_nil_do_end_end_do_end;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_var_and_prefixexp():
    """
    Test parsing "var"s and "prefixexp"s (from the Lua grammar)
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():

        # ======== Var ========
        parse_lua('a = 1 ;_'.replace(' ', ws).replace('_', ws_sep))                       # (none)
        parse_lua('a [ -23 ] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))               # [exp]
        parse_lua('a . b = 1 ;_'.replace(' ', ws).replace('_', ws_sep))                   # .name
        with pytest.raises(Exception):
            parse_lua('a : b = 1 ;_'.replace(' ', ws).replace('_', ws_sep))               # :name, with no args
        with pytest.raises(Exception):
            parse_lua('a : b ( 1 , 2 ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))     # :name (args)
        with pytest.raises(Exception):
            parse_lua("a : b 'arg' = 1 ;_".replace(' ', ws).replace('_', ws_sep))         # :name 'string argument'
        with pytest.raises(Exception):
            parse_lua('a : b "arg" = 1 ;_'.replace(' ', ws).replace('_', ws_sep))         # :name "string argument"
        with pytest.raises(Exception):
            parse_lua('a : b [[arg]] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))       # :name [[string argument]]
        with pytest.raises(Exception):
            parse_lua('a : b [==[arg]==] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))   # :name [==[string argument]==]
        with pytest.raises(Exception):
            parse_lua('a : b { 1 , 2 ; 3 } = 1 ;_'.replace(' ', ws).replace('_', ws_sep)) # :name {table constructor argument}
        with pytest.raises(Exception):
            parse_lua('a ( 1 , 2 ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))         # (args)
        with pytest.raises(Exception):
            parse_lua('a ( ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))               # ()
        with pytest.raises(Exception):
            parse_lua("a 'arg' = 1 ;_".replace(' ', ws).replace('_', ws_sep))             # 'string argument'
        with pytest.raises(Exception):
            parse_lua('a "arg" = 1 ;_'.replace(' ', ws).replace('_', ws_sep))             # "string argument"
        with pytest.raises(Exception):
            parse_lua('a [[ arg ]] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))         # [[string argument]]
        with pytest.raises(Exception):
            parse_lua('a [==[arg]==] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))       # [==[string argument]==]
        with pytest.raises(Exception):
            parse_lua('a { 1 , 2 ; 3 } = 1 ;_'.replace(' ', ws).replace('_', ws_sep))     # {table constructor argument}

        # Test chaining multiple parts

        parse_lua('a ( b ) . c [ e ] "f" [[g]] [ h . i ] = 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a ( b ) . c [ e ] "f" [[g]] [ h . i ] ( ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))

        parse_lua('a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) . j = 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) = 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) "j" = 1 ;_'.replace(' ', ws).replace('_', ws_sep))

        # ======== Prefixexp ========
        for exp in ['nil', '1', '-23']: # important to check that negative numbers work
            parse_lua( 'a = a ;_'.replace(' ', ws).replace('_', ws_sep))                                 # (none)
            parse_lua(f'a = a [ {exp} ] ;_'.replace(' ', ws).replace('_', ws_sep))                       # [exp]
            parse_lua( 'a = a . b ;_'.replace(' ', ws).replace('_', ws_sep))                             # .name
            parse_lua(f'a = a : b ( {exp} , {exp} ) ;_'.replace(' ', ws).replace('_', ws_sep))           # :name (args)
            parse_lua( "a = a : b 'arg' ;_".replace(' ', ws).replace('_', ws_sep))                       # :name 'string argument'
            parse_lua( 'a = a : b "arg" ;_'.replace(' ', ws).replace('_', ws_sep))                       # :name "string argument"
            parse_lua( 'a = a : b [[arg]] ;_'.replace(' ', ws).replace('_', ws_sep))                     # :name [[string argument]]
            parse_lua( 'a = a : b [==[arg]==] ;_'.replace(' ', ws).replace('_', ws_sep))                 # :name [==[string argument]==]
            parse_lua(f'a = a : b {{ {exp} , {exp} ; {exp} }} ;_'.replace(' ', ws).replace('_', ws_sep)) # :name {table constructor argument}
            parse_lua(f'a = a ( {exp} , {exp} ) ;_'.replace(' ', ws).replace('_', ws_sep))               # (args)
            parse_lua( "a = a 'arg' ;_".replace(' ', ws).replace('_', ws_sep))                           # 'string argument'
            parse_lua( 'a = a "arg" ;_'.replace(' ', ws).replace('_', ws_sep))                           # "string argument"
            parse_lua( 'a = a [[arg]] ;_'.replace(' ', ws).replace('_', ws_sep))                         # [[string argument]]
            parse_lua( 'a = a [==[arg]==] ;_'.replace(' ', ws).replace('_', ws_sep))                     # [==[string argument]==]
            parse_lua(f'a = a {{ {exp} , {exp} ; {exp} }} ;_'.replace(' ', ws).replace('_', ws_sep))     # {table constructor argument}
        with pytest.raises(Exception):
            parse_lua( 'a = a : b ;_'.replace(' ', ws).replace('_', ws_sep))                             # :name, with no args

        # Test chaining multiple parts

        parse_lua('a = a ( b ) . c [ e ] "f" [[g]] [ h . i ] ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = a ( b ) . c [ e ] "f" [[g]] [ h . i ] : j ;_'.replace(' ', ws).replace('_', ws_sep))

        parse_lua('a = a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) . j ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = a [=[b]=] [ c ] \'d\' { e } . f . g : h ( i ) : j ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_singleton_expression():
    """
    Test parsing expressions "nil", "false", "true", and "..."
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        for semicolon in ['_', ';']:
            for exp in ['_nil', '_false', '_true', '...']:
                parse_lua(f'do_return {exp}{semicolon}end_do_end ;_'.replace(' ', ws).replace('_', ws_sep))
                parse_lua(f'a = {exp} , {exp} {semicolon}'.replace(' ', ws).replace('_', ws_sep))

        with pytest.raises(Exception):
            parse_lua('a = ._'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = .._'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = .;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = ..;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_numeral_expression():
    """
    Test parsing numeral expressions
    """
    reset_counter()
    # There are a lot of possible numbers, and it's easy to miss some
    # cases, so we'll generate a representative case for pretty much
    # every situation.

    # Make some lists of digit sequences.
    # "0" is handled specially in the parser for the purposes of detecting
    # "0x", so it's important to test sequences beginning with that.
    # Also, be sure these are lowercase, since uppercase versions are tested automatically.
    # Also, ".0" and "0." are both valid ways of writing "0.0" but you
    # *can't* write just "0e", so only include the empty string in the former
    # two situations
    decDigitSequences = ['0', '01', '012', '1', '123']
    hexDigitSequences = decDigitSequences + ['e', 'f', '1e2', '0a1b2c']

    # Test both hex and decimal...
    for isHex in [False, True]:
        digitSequences = (hexDigitSequences if isHex else decDigitSequences)

        # First few digits (which can be empty)
        for leadingDigits in digitSequences + ['']:

            # Optional fractional part (which can be just a "." with no following digits,
            # but only if the leading digits are nonempty)
            fractionalParts = ['.' + s for s in digitSequences]
            if leadingDigits: fractionalParts += ['', '.']
            for fractionalPart in fractionalParts:

                # Sign for the optional exponent part
                for expSign in ['', '-', '+']:

                    # Optional exponential part (which is in decimal no matter what)
                    expSep = 'p' if isHex else 'e'
                    for exponentPart in [''] + [expSep + expSign + s for s in decDigitSequences]:

                        # Construct the number, in both lowercase and uppercase
                        expL = ('0x' if isHex else '') + leadingDigits + fractionalPart + exponentPart
                        expU = expL.upper()

                        # Try to parse both types
                        parse_lua(f'a = {expL} ; ')
                        parse_lua(f'a = {expU} ; ')

    with pytest.raises(Exception):
        parse_lua('a = 0D2 ; ')
    with pytest.raises(Exception):
        parse_lua('a = 5D2 ; ')
    with pytest.raises(Exception):
        parse_lua('a = 0x ; ')
    with pytest.raises(Exception):
        parse_lua('a = 12e ; ')
    with pytest.raises(Exception):
        parse_lua('a = 0x34p ; ')
    with pytest.raises(Exception):
        parse_lua('a = 0x34pFE ; ')
    with pytest.raises(Exception):
        parse_lua('a = . ; ')
    with pytest.raises(Exception):
        parse_lua('a = .e5 ; ')

    # Note: llex.c mentions "3-4" and "0xe+1" as test cases that should be
    # parsed as expressions rather than single numbers. There's no way to
    # test for this, though, since, in every context where a number can be
    # used, an expression would be also accepted instead.

    # Additional tests from Lua test suite (literals.lua):
    with pytest.raises(Exception):
        parse_lua('a = 0xe- ; ')
    with pytest.raises(Exception):
        parse_lua('a = 0xep-p ; ')
    end()


def test_string_expression():
    """
    Test parsing string expressions
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        if '\n' in ws: continue # causes too many problems

        # Test short-form strings
        for quote, opposite_quote in [('"' "'"), ("'" '"')]:
            parse_lua(f'a = {quote} hello {opposite_quote} world {quote} ;_'.replace(' ', ws).replace('_', ws_sep))

        # Test simple escapes
        for esc in ('abfnrtv' '\\' '"' "'" '\n'):
            parse_lua(f'a = "hello\\{esc}world" ;_'.replace(' ', ws).replace('_', ws_sep))

        # \z: skips following whitespace, including newlines
        if '--' not in ws:
            parse_lua(f'a = "hello \\z \t \r \n world" ;_'.replace(' ', ws).replace('_', ws_sep))

        # \xXX hex escapes
        parse_lua(r'a = "hello \x00 \xfF \x78 world" ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(r'a = "hello \x2 world" ;_'.replace(' ', ws).replace('_', ws_sep))

        # \d, \dd, \ddd decimal escapes
        parse_lua(r'a = "hello \1 \12 \123 \1234 world" ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(r'a = "hello \240 \250 \255 \25599 \255F world" ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(r'a = "hello \2a \25a \255a world" ;_'.replace(' ', ws).replace('_', ws_sep))
        for v in ['256', '260', '300', '999']:
            with pytest.raises(Exception):
                parse_lua(f'a = "hello \\{v} world" ;_'.replace(' ', ws).replace('_', ws_sep))

        # \u{XXX} unicode literals
        parse_lua(r'a = "hello \u{0} \u{1234CDEF} \u{0001234CDEF} world" ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua(r'a = "hello \u{7FFFFFFF} \u{0007FFFFFFF} world" ;_'.replace(' ', ws).replace('_', ws_sep))
        for v in ['700000000', '7FFFFFFF0', '80000000', '8FFFFFFF', 'FFFFFFFF']:
            with pytest.raises(Exception):
                parse_lua(f'a = "hello \\u{v} world" ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua(r'a = "hello \u{} world" ;_'.replace(' ', ws).replace('_', ws_sep))

        # Test illegal linebreaks
        with pytest.raises(Exception):
            parse_lua(f'a = "hello\nworld" ;_'.replace(' ', ws).replace('_', ws_sep))

        # Test some random invalid escapes
        for esc in 'cdyq!#*':
            with pytest.raises(Exception):
                parse_lua(f'a = "hello\\{esc}world" ;_'.replace(' ', ws).replace('_', ws_sep))

    # Test non-ASCII characters
    parse_lua(f'a = " ツ " ; '.encode('utf-8'))

    # Test long-form strings
    # These ignore escape sequences so we don't have to test that
    helper_test_multiline_comment_or_long_string('a =')
    end()


def test_function_expression():
    """
    Test parsing function expressions
    """
    reset_counter()
    helper_test_function_bodies('a = function')
    end()


def test_table_constructor_expression():
    """
    Test parsing table constructor expressions
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        # Empty table constructors, with varying whitespace
        parse_lua('a = { } ;_'.replace(' ', ws).replace('_', ws_sep))

        # Field format: [exp] = exp
        parse_lua('a = { [ 5 ] = 5 } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { [ b . c : e ( f ) ] = g ( h ) . i [ nil ] } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { [ b . c : e ( f ) ] = g ( h ) . i [ -23 ] ; } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { [ b . c : e ( f ) ] = g ( h ) . i [ ... ] , } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { [ 5 ] } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { [ 5 ] = } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { [ for ] = nil } ;_'.replace(' ', ws).replace('_', ws_sep))

        # Field format: name = exp
        parse_lua('a = { five = 5 } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { a = g ( h ) . i [ nil ] } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { a = g ( h ) . i [ -23 ] ; } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { a = g ( h ) . i [ ... ] , } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { five = } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { 7 = 5 } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { nil = 5 } ;_'.replace(' ', ws).replace('_', ws_sep))

        # Field format: exp
        parse_lua('a = { 5 } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { b . c : e ( f ) } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { g ( h ) . i [ nil ] } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { g ( h ) . i [ -23 ] ; } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { g ( h ) . i [ ... ] , } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { nil } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { five } ;_'.replace(' ', ws).replace('_', ws_sep))
        if '[[' not in ws:
            parse_lua('a = { [[ [long string starting with single square bracket ]] } ;_'.replace(' ', ws).replace('_', ws_sep))
            parse_lua('a = { [[ [long string starting with single square bracket ]] , } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { 5 = } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { [[ [this should be a syntax error]] ] } ;_'.replace(' ', ws).replace('_', ws_sep))

        # Multiple fields
        parse_lua('a = { 5 , 6 , 7 } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { 5 , fish ; hello = "world" } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { 5 ; fish , hello = "world" } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { hello = "world" ; [ a . b ] = 33 } ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = { -23 } ;_'.replace(' ', ws).replace('_', ws_sep))

        # An example from the Lua documentation
        parse_lua('a = { [ f ( 1 ) ] = g ; "x" , "y" ; x = 1 , f ( x ) , [ 30 ] = 23 ; 45 } ;_'.replace(' ', ws).replace('_', ws_sep))

        # Table constructors with only a field separator (illegal)
        with pytest.raises(Exception):
            parse_lua('a = { , } ;_'.replace(' ', ws).replace('_', ws_sep))
        with pytest.raises(Exception):
            parse_lua('a = { ; } ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_binary_operator_expression():
    """
    Test parsing binary-operator expressions
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        for op1 in 'b2':
            for op2 in 'c3':
                for binop in [' + ', ' - ', ' * ', ' / ', ' // ', ' ^ ', ' % ',
                        ' & ', ' ~ ', ' | ', ' >> ', ' << ', ' .. ',
                        ' < ', ' <= ', ' > ', ' >= ', ' == ', ' ~= ',
                        '_and_', '_or_']:

                    if '-' in ws and '-' in binop: continue   # too much trouble
                    if '.' in binop and op1 == '2': continue  # "a = 2..c" is read by Lua as a malformed
                                                              # number, not a binary operator exp

                    parse_lua(f'a = {op1}{binop}{op2} ;_'.replace(' ', ws).replace('_', ws_sep))

    # Special case that used to trip the parser up:
    # situations where it thinks it's going to read "x and y" but it
    # turns out that the "a" is actually the start of the next statement
    parse_lua('local_a = 5_a ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    parse_lua('local_a = 5_az ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    parse_lua('local_a = 5_an ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    parse_lua('local_a = 5_anz ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    with pytest.raises(Exception):
        parse_lua('local_a = 5_and ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    parse_lua('local_a = 5_andz ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))

    # (Making it a two-element expression list triggers a slightly
    # different code path)
    parse_lua('local_a = 5 , 6 andz ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))

    # (And same for "or")
    parse_lua('local_a = 5_o ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    parse_lua('local_a = 5_oz ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    with pytest.raises(Exception):
        parse_lua('local_a = 5_or ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    parse_lua('local_a = 5_orz ( nil , nil ) ;_'.replace(' ', ws).replace('_', ws_sep))
    end()


def test_unary_operator_expression():
    """
    Test parsing unary-operator expressions
    """
    reset_counter()
    for ws, ws_sep in iter_whitespace():
        parse_lua('a = - 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = not_1 ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = # 1 ;_'.replace(' ', ws).replace('_', ws_sep))
        parse_lua('a = ~ 1 ;_'.replace(' ', ws).replace('_', ws_sep))
    end()
