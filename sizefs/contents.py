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
#                | "(" <Expression> ")" [<Multiplier>]
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
        self.components = self.__parse_xeger__(regex)
        self.max_random = max_random
        self.__parse_xeger__(regex)

    def __parse_expressions__(self, regex):
        self.expressions = []
        regex_list = list(regex)
        while regex_list:
            expression = XegerExpression(regex_list, self.max_random)
            self.expressions.append(expression)

    def generate_prefix(self):
        prefix = self.expressions[0].generate_complete()
        self.expressions = self.expressions[1:]
        return prefix

    def generate_suffix(self):
        suffix = self.expressions[-1].generate_complete()
        self.expressions = self.expressions[:-1]
        return suffix

    def generate(self):
        while True:
            for expression in self.expressions:
                yield expression.generate()

    def generate_complete(self):
        generated_content = []
        for expression in self.expressions:
            generated_content.append(expression.generate_complete())
        return "".join(generated_content)


class XegerExpression(AbstractXegerGenerator):
    """
    Parses an Expression from a list of input characters
    """

    def __init__(self, regex_list, max_random=128):
        self.__max_random__ = max_random
        self.__get_generator__(regex_list)


    # need to make sure regex isn't "" in the two methods below...
    def __get_generator__(self, regex):
        accum = []

        while regex:
            c = regex.pop(0)
            if c == '(':  # We've reached what appears to be a nested expression
                if not accum:  # We've not accumulated any content to return
                    accum = self.__get_nested_expression__(regex)
                    self.__generator__ = XegerExpression(accum,
                                                         self.__max_random__)
                    self.__multiplier__ = XegerMultiplier(regex)
                    self.__is_constant_multiplier__()
                    break
                else:  # There is info in the accumulator, so it much be chars
                    regex.insert(0, c)
                    self.__generator__ = XegerChars(accum)
                    self.__constant_multiplier__ = True
                    self.__multiplier__ = 1
                    break
            elif c == '[':  # We've reached the start of a set
                if not accum:  # If nothing in accumulator, just process set
                    accum = self.__get_range__(regex)
                    self.__generator__ = XegerRange(accum)
                    self.__multiplier__ = XegerMultiplier(regex)
                    self.__is_constant_multiplier__()
                    break
                else:  # There's already stuff in the accumulator, must be chars
                    regex.insert(0, c)
                    self.__generator__ = XegerChars(accum)
                    self.__constant_multiplier__ = True
                    self.__multiplier__ = 1
                    break
            elif c == '\\':  # Escape the next character
                accum.append(c)
                c = regex.pop(0)
                accum.append(c)
            elif c in ['{', '*', '+']:  # We've reached a multiplier
                if len(accum) == 1:  # just multiply a single character
                    self.__generator__ = XegerChars(accum)
                    self.__multiplier__ = XegerMultiplier(regex.insert(0, c))
                    self.__is_constant_multiplier__()
                    break
                elif len(accum) > 1:  # only multiply the last character
                    last_c = accum[-1]
                    regex.insert(0, c)
                    regex.insert(0, last_c)
                    self.__generator__ = XegerChars(accum[:-1])
                    self.__multiplier__ = XegerMultiplier(regex)
                    self.__is_constant_multiplier__()
                    break
            else:  # just keep collecting boring characters
                accum.append(c)

        if accum:  # If there's anything left in the accumulator, must be chars
            self.__generator__ = XegerChars(accum)
            self.__constant_multiplier__ = True
            self.__multiplier__ = 1

    def __is_constant_multiplier__(self):
        if not self.__multiplier__.random:
            self.__constant_multiplier__ = True
            self.__multiplier__ = self.__multiplier__.generate()
        else:
            self.__constant_multiplier__ = False

    def __get_nested_expression__(self, regex):
        accum = []

        while regex:
            c = regex.pop(0)
            if c == '(':
                accum.append('(')
                accum += self.__get_nested_expression__(regex)
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
            else:
                if started:
                    try:
                        int(c)
                        mult.append(c)
                    except:
                        raise XegerError("Multipler must be a number")
                else:
                    self.random = False
                    self.constant = 1

        raise XegerError("Incomplete multiplier")

    def generate(self):
        if not self.random:
            return self.constant
        else:
            return random.randint(self.min_random, self.max_random)

#
#elif c == ')':
            #    mult = self.__get_multiplier__(regex)
            #    return XegerChars(accum), mult
#elif c == ']':
            #    mult = self.__get_multiplier__(regex)
            #    return XegerExpression(accum, mult)