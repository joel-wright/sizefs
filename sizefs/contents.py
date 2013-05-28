import random
import itertools
import logging


class XegerError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


# BNF for acceptable Regex:
#
#   <Regex> ::= ["^"] <Pattern> ["$"]
#
#   <Pattern> ::= <Expression>
#             | <Expression> <Pattern>
#
#   <Expression> ::= <Char> [<Multiplier>]
#                | "(" <Pattern> ")" [<Multiplier>]
#                | "[" <Set> "]" [<Multiplier>]
#
#   <Multiplier> ::= "*"
#                | "+"
#                | '{' <Num> '}'
#
#   <Set> ::= <Char>
#           | <Char> "-" <Char>
#           | <Set> <Set>

class XegerGen(object):
    """
    Generate regex content through the read method defined by a given pattern.

    Only fully supports sequential reading, however, any read within any
    specified start or end range will produce an appropriate output (this is
    necessary for metadata testing functions.
    """

    def __init__(self, regex, size, max_random=128):
        self.size = size
        self.max_random = max_random
        self.index = 0
        self.xeger = Xeger(regex, self.max_random)
        self.prefix = self.xeger.prefix
        self.suffix = self.xeger.suffix

    def __read__(self, start, end):
        # Need to sort out a read strategy
        # The pattern should repeat if possible (i.e. *,+)
        # Should only run through the input list once...
        # Dumb regexs are just that... dumb
        # Special case in which a */+ is the last in a sequence
        #  - will be repeated over and over
        return ""


class AbstractXegerGenerator(object):
    def generate(self):
        raise NotImplementedError

    def generate_complete(self):
        raise NotImplementedError


class Xeger(AbstractXegerGenerator):
    """
    Parses a given regex pattern and yields content on demand.

    Prefix and suffix patterns are generated, stored and removed from the
    regenerated components to allow for consistent reading of these portions
    from the file generated (to support metadata checking)
    """

    def __init__(self, regex, max_random=128):
        self.max_random = max_random
        self.__parse_pattern__(regex)

    def __parse_pattern__(self, regex):
        if regex.startswith('^'):
            fixed_start = True
            regex = regex[1:]

        if regex.endswith('$'):
            fixed_end = True
            regex = regex[:-1]

        self.pattern = XegerPattern(regex, self.max_random)

        if fixed_start:
            self.prefix = self.pattern.generate_prefix()

        if fixed_end:
            self.suffix = self.pattern.generate_suffix()

    def generate(self):
        while True:
            for content in self.pattern.generate():
                yield content

    def generate_complete(self):
        generated_content = []
        for expression in self.expressions:
            generated_content.append(expression.generate_complete())
        return "".join(generated_content)


class XegerPattern(AbstractXegerGenerator):
    """
    Parses a given pattern into a list of XegerExpressions

    This generates a list of top-level expressions that can be used to generate
    the contents of a file.
    """

    def __init__(self, regex, max_random=128):
        self.__max_random__ = max_random
        self.__parse_expressions__(regex)

    def __parse_expressions__(self, regex):
        self.__expressions__ = []
        regex_list = list(regex)
        while regex_list:
            expression = XegerExpression(regex_list, self.__max_random__)
            self.__expressions__.append(expression)

    def generate_prefix(self):
        prefix = self.__expressions__[0].generate_complete()
        self.__expressions__ = self.__expressions__[1:]
        return prefix

    def generate_suffix(self):
        suffix = self.__expressions__[-1].generate_complete()
        self.__expressions__ = self.__expressions__[:-1]
        return suffix

    def length(self):
        return len(self.__expressions__)

    def generate(self):
        while True:
            for expression in self.__expressions__:
                yield expression.generate()

    def generate_complete(self):
        generated_content = []
        for expression in self.__expressions__:
            generated_content.append(expression.generate_complete())
        return "".join(generated_content)


class XegerExpression(AbstractXegerGenerator):
    """
    Parses an Expression from a list of input characters
    """

    def __init__(self, regex_list, max_random=128):
        self.__max_random__ = max_random
        self.__get_generator__(regex_list)

    def __get_generator__(self, regex):
        accum = []

        while regex:
            c = regex.pop(0)
            if c == '(':  # We've reached what appears to be a nested expression
                if not accum:  # We've not accumulated any content to return
                    accum = self.__get_nested_pattern_input__(regex)
                    self.__generator__ = XegerPattern(accum,
                                                      self.__max_random__)
                    self.__multiplier__ = XegerMultiplier(regex)
                    self.__is_constant_multiplier__()
                    return
                else:  # There is info in the accumulator, so it much be chars
                    regex.insert(0, c)
                    self.__generator__ = XegerSequence(accum)
                    self.__constant_multiplier__ = True
                    self.__multiplier__ = 1
                    return
            elif c == '[':  # We've reached the start of a set
                if not accum:  # If nothing in accumulator, just process set
                    self.__generator__ = XegerSet(regex)
                    self.__multiplier__ = XegerMultiplier(regex)
                    self.__is_constant_multiplier__()
                    return
                else:  # There's already stuff in the accumulator, must be chars
                    regex.insert(0, c)
                    self.__generator__ = XegerSequence(accum)
                    self.__constant_multiplier__ = True
                    self.__multiplier__ = 1
                    return
            elif c == '\\':  # Escape the next character
                accum.append(c)
                c = regex.pop(0)
                accum.append(c)
            elif c in ['{', '*', '+']:  # We've reached a multiplier
                if len(accum) == 1:  # just multiply a single character
                    self.__generator__ = XegerSequence(accum)
                    self.__multiplier__ = XegerMultiplier(regex.insert(0, c))
                    self.__is_constant_multiplier__()
                    return
                elif len(accum) > 1:  # only multiply the last character
                    last_c = accum[-1]
                    regex.insert(0, c)
                    regex.insert(0, last_c)
                    self.__generator__ = XegerSequence(accum[:-1])
                    self.__multiplier__ = XegerMultiplier(regex)
                    self.__is_constant_multiplier__()
                    return
            else:  # just keep collecting boring characters
                accum.append(c)

        if accum:  # If there's anything left in the accumulator, must be chars
            self.__generator__ = XegerSequence(accum)
            self.__constant_multiplier__ = True
            self.__multiplier__ = 1

    def __is_constant_multiplier__(self):
        if not self.__multiplier__.random:
            self.__constant_multiplier__ = True
            self.__multiplier__ = self.__multiplier__.generate()
        else:
            self.__constant_multiplier__ = False

    def __get_nested_pattern_input__(self, regex):
        accum = []

        while regex:
            c = regex.pop(0)
            if c == '(':
                accum.append('(')
                accum += self.__get_nested_pattern_input__(regex)
                accum.append(')')
            elif c == ')':
                return accum
            else:
                accum.append(c)

        raise XegerError("Incomplete expression")

    def generate(self):
        while True:
            yield self.__generator__.generate()

    def generate_complete(self):
        self.__generator__.generate_complete()


class XegerMultiplier(object):
    """
    Represents a multiplier
    """

    def __init__(self, regex, max_random=128):
        self.max_random = max_random
        self.__get_multiplier__(regex)

    def __get_multiplier__(self, regex):
        mult = []
        started = False

        while regex:
            c = regex.pop(0)
            if c == '{':
                if mult:
                    raise XegerError("Error in multiplier pattern")
                started = True
            elif c == '}':
                if mult:
                    self.random = False
                    self.constant = int("".join(mult))
                    return
                else:
                    raise XegerError("Illegal end of multiplier pattern")
            elif c in ['*', '+']:
                if started:
                    raise XegerError("Error in multiplier pattern")
                else:
                    self.random = True
                    if c == '+':
                        self.min_random = 1
                    else:
                        self.min_random = 0
                    return
            else:
                if started:
                    try:
                        int(c)
                        mult.append(c)
                    except:
                        raise XegerError("Multipler must be a number")
                else:
                    break

        if started:
            raise XegerError("Incomplete multiplier")
        else:
            self.random = False
            self.constant = 1

    def generate(self):
        if not self.random:
            return self.constant
        else:
            return random.randint(self.min_random, self.max_random)


class XegerSequence(AbstractXegerGenerator):
    """
    Simple generator, just returns the sequence on each call to generate
    """

    def __init__(self, list):
        self.sequence = "".join(list)

    def generate(self):
        return self.sequence

    def generate_complete(self):
        return self.sequence


class XegerSet(AbstractXegerGenerator):
    """
    Set generator, parses an input list for a set and returns a single element
    on each call to generate (generate_complete is identical)
    """

    def __init__(self, regex):
        self.__parse_set__(regex)

    def __parse_set__(self, regex):
        select_list = []
        ch1 = ''

        while regex:
            c = regex.pop(0)
            if c == ']':
                if not ch1 == '':
                    select_list.append(ch1)
                    self.__set__ = select_list
                    return
                else:
                    raise XegerError("Error in set description")
            elif c == '-':
                if ch1 == '':
                    raise XegerError("Error in set description")
                elif len(regex) == 0:
                    raise XegerError("Incomplete set description")
                else:
                    ch2 = regex.pop(0)
                    set_extras = self.__char_range__(ch1, ch2)
                    for extra in set_extras:
                        select_list.append(extra)
                    ch1 = ''
            else:
                ch1 = c

        # The range was incomplete because we never reached the closing brace
        raise XegerError("Incomplete set description")

    def __char_range__(self, a, b):
        for c in xrange(ord(a), ord(b) + 1):
            yield chr(c)

