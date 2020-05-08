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


def _print_nice_indicator(s, i):
    """
    Print a nice indicator showing the position of the character at
    index "i" in bytes "s"
    """
    newline_before = s.rfind(b'\n', 0, i - 1)
    newline_after = s.find(b'\n', i)
    line = repr(s[newline_before + 1 : newline_after])[2:-1]  # "b'" and "'"
    i -= newline_before + 1

    line_num = s.count(b'\n', 0, i - 1) + 1
    line_num_str = f'[line {line_num}]'
    print(line_num_str, line)
    print(' ' * (len(line_num_str) + 1) + '-' * i + '^')



class TwoPDA:
    """
    Class implementing a 2PDA (two-way pushdown automaton)
    """
    # name: just a nice string name
    name = ''

    # transitions: a dictionary of
    #     (state_name, character, stack_top_or_None) -> (new_state, direction, stack_op, stack_value)
    #     where
    # - state_name: name of starting state
    # - character: character to read
    # - stack_top_or_None: the value required to be on top of the stack
    #   for the transition to be taken, or None if it doesn't matter.
    #   Transitions with a specified stack-top value take precedence
    #   over None's, if both match.
    # - new_state: name of destination state
    # - direction ("right"|"stay"): direction to move in the input
    #   string
    # - stack_op ("push"|"pop"|"read"|"replace"):
    #    - push: push stack_value onto the stack
    #    - pop: pop whatever's on top of the stack
    #    - read: don't modify the stack
    #    - replace: "pop" followed by "push"
    transitions = None

    # initial_state: the state to begin at
    initial_state = None

    def __init__(self):
        self.state = self.initial_state
        self.stack = []


    def parse(self, input, *, debug_level=0):
        """
        Parse an input string (a sequence of characters)
        """
        if debug_level >= 2:
            print(f'\n(Starting to parse string starting with {repr(input[:60])}.)')
        i = 0
        while i < len(input):
            try:
                c = bytes([input[i]])
                direction = self.consume_character(c, debug_level=debug_level, debug_i=i)

            except:
                if debug_level >= 1:
                    # Print some useful debug stuff
                    print('Error occurs here:')
                    _print_nice_indicator(input, i)
                    print('State is:                ', self.state)
                    print('Stack (bottom to top) is:', ', '.join(self.stack))
                    print('Parsed character is:     ', input[i], f'(pos. {i})')

                raise RuntimeError(f'Error parsing input string starting with "{input[:20].decode("latin-1")}", at index {i}')

            if direction == 'right':
                i += 1


    def consume_character(self, c, *, debug_level=0, debug_i=0):
        """
        Parse a single character and take the appropriate transition.
        Return the direction ("right"|"stay") to move in the input
        string.
        """
        transitionsKey = None
        if self.stack:
            transitionsKey = (self.state, c, self.stack[-1])
        if transitionsKey not in self.transitions:
            transitionsKey = (self.state, c, None)
            if transitionsKey not in self.transitions:
                raise RuntimeError(f'No transition found for "{c}" (state: {self.state}; stack: {self.stack})')

        newState, direction, op, value = self.transitions[transitionsKey]
        if debug_level >= 3:
            print(f'    Following {transitionsKey} -> {self.transitions[transitionsKey]}')

        if op == 'push':
            self.stack.append(value)
        elif op == 'pop':
            self.stack.pop()
        elif op == 'read':
            pass
        elif op == 'replace':
            self.stack[-1] = value
        else:
            raise RuntimeError(f'Unknown transition op: "{op}"')

        self.state = newState

        if debug_level >= 2:
            print(repr(c)[1:-1], f'({debug_i})', self.stack, self.state)

        return direction


    @classmethod
    def print_stats(cls):
        """
        Convenience function to print some statistics about the 2PDA
        """

        states = set()
        stack_symbols = set()
        for a, b in cls.transitions.items():
            try:
                (state_name, character, stack_top_or_None) = a
                (new_state, direction, stack_op, stack_value) = b
            except ValueError:
                print('Incorrectly formatted transition:', a, b)
                raise

            if not isinstance(character, bytes):
                raise ValueError(a, b)

            states.add(state_name)
            states.add(new_state)
            stack_symbols.add(stack_top_or_None)
            stack_symbols.add(stack_value)

        print(f'Stats about {cls.name} 2PDA:')
        print('Number of states:', len(states))
        print('Number of transitions:', len(cls.transitions))
        print('Number of stack symbols:', len(stack_symbols))
