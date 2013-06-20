import random
import logging


class FastRandom(object):
    """
    random itself is too slow for our purposes, so we use random to populate
    a small list of randomly generated numbers that can be used in each call
    to randint()

    A call to randint() just returns the a number from our list and increments
    the list index.

    This is faster and good enough for a "random" filler
    """
    def __init__(self, min, max, len=255):
        # Generate a small list of random numbers
        self.randoms = [random.randint(min, max) for i in range(len)]
        self.index = 0
        self.len = len

    def rand(self):
        value = self.randoms[self.index]
        if self.index < self.len - 1:
            self.index += 1
        else:
            self.index = 0
        return value


class XegerError(Exception):
    """
    Exception type for reporting Xeger generation errors
    """
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class XegerGen(object):
    """
    The generator uses up to 4 regular expressions to generate the contents
    of a file defined below:

     - prefix: fixed start to the file
               defaults to ""
     - suffix: fixed end to the file
               defaults to ""
     - filler: the repeating body of the file (the body of the file always
               amounts to (filler)*
               defaults to 0*
     - padder: if a complex filler pattern generated does not fit within
               the remaining space left in the generated file, padding
               is used to fill the remaining space. This should always be
               as simple as possible (preferably generating individual
               characters).
               defaults to 0*

    The file will be generated as follows: (prefix)(filler)*(padder)*(suffix)

    BNF for acceptable Xeger patterns:

      <Xeger> ::= <Pattern>

      <Pattern> ::= <Expression>
                | <Expression> <Pattern>

      <Expression> ::= <Char> [<Multiplier>]
                   | "(" <Pattern> ")" [<Multiplier>]
                   | "[" <Set> "]" [<Multiplier>]

      <Multiplier> ::= "*"
                   | "+"
                   | "?"
                   | '{' <Num> '}'

      <Set> ::= <Char>
              | <Char> "-" <Char>
              | <Set> <Set>

    The generator will always produce a string containing the prefix and
    suffix if a string of sufficient size is requested. Following that, the
    generator will fill the remaining space with filler, either ending there
    or filling remaining space using the padder pattern. The padder pattern
    will only be used if a complete filler pattern will not fit in the space
    remaining.

    max_random is used to define the largest random repeat factor of any
    + or * operators.

    Random seeks within a file may produce inconsistent results for general
    file contents, however prefix and suffix will always be consistent with
    the requested pattern.
    """
    def __init__(self, size, filler=None, prefix=None,
                 suffix=None, padder=None, max_random=128):
        self.size = size
        self.random = FastRandom(max_random)
        self.logger = logging.getLogger(__name__)

        if filler is not None:
            self.filler = Xeger(filler, self.random)
        else:
            self.filler = Xeger("0", self.random)

        if padder is not None:
            self.padder = Xeger(padder, self.random)
        else:
            self.padder = Xeger("0", self.random)

        if prefix is not None:
            self.prefix = Xeger(prefix, self.random).generate_complete()
            self.prefix_length = len(self.prefix)
        else:
            self.prefix = ""
            self.prefix_length = 0

        if suffix is not None:
            self.suffix = Xeger(suffix, self.random).generate_complete()
            self.suffix_length = len(self.suffix)
        else:
            self.suffix = ""
            self.suffix_length = 0

        if size < (self.prefix_length + self.suffix_length):
            self.logger.error("Prefix and suffix combination is longer than"
                              "the requested size of the file. One or both will"
                              "be truncated")

    def __read__(self, start, end):
        """
        Return regex content.

        Only fully supports sequential reading, however, any read with start or
        end range within a specified prefix or suffix pattern will produce
        appropriate output (this is necessary for metadata testing functions).
        """
        if not start == self.end_last_read + 1:
            # If we're not reading sequentially, get rid of any remainder
            self.remainder = ""

        self.end_last_read = end

        if start < self.suffix_length:
            self.remainder = ""
            content = self.suffix[start:]
        else:
            content = self.remainder

        chunk_size = end - start

        # This look horrendous
        # TODO: tidy up the read logic
        if end > (self.size - self.suffix_length):
            # If we're sufficiently close to the end size of the contents
            # requested, then we need to consider padding and suffix
            last = self.suffix[:self.size - end]
            content_length = len(content)
            more = self.remainder
            while len(content) < (chunk_size - len(last)):
                more += self.filler.generate()
                still_required = chunk_size - content_length - len(last)
                if len(more) > still_required:
                    pad = self.__get_padding__(still_required)
                    content += pad
                    content += last
                    return content
                else:
                    content += more
                    content += last
        else:
            content_length = len(content)
            more = self.remainder
            while len(content) < chunk_size:
                more += self.filler.generate()
                still_required = chunk_size - content_length
                if len(more) > still_required:
                    overrun = len(more) - still_required
                    if (end + overrun) > (self.size - self.prefix_length):
                        final = self.__get_padding__(still_required)
                        self.remainder = self.__get_padding__(overrun)
                    else:
                        self.remainder = more[still_required:]
                        final = more[:still_required]
                    content += final
                    return content
                else:
                    content += more

    def __get_padding__(self, size):
        pad = ""
        while len(pad) < size:
            pad += self.padder.generate()
        return pad[:size]


class Xeger(object):
    """
    Parses a given regex pattern and yields content on demand.

    Prefix and suffix patterns are generated, stored and removed from the
    regenerated components to allow for consistent reading of these portions
    from the file generated (to support metadata checking)
    """
    def __init__(self, regex, size, random):
        self.random = random
        self.__size__ = size
        self.pattern = XegerPattern(regex, self.random)

    def generate(self):
        while True:
            for content in self.pattern.generate():
                yield content

    def generate_complete(self):
        generated_content = []
        for expression in self.expressions:
            generated_content.append(expression.generate_complete())
        return "".join(generated_content)


class XegerPattern(object):
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
        if self.length() > 0:
            prefix = self.__expressions__[0].generate_complete()
            self.__expressions__ = self.__expressions__[1:]
            return prefix
        else:
            return ""

    def generate_suffix(self):
        if self.length() > 0:
            suffix = self.__expressions__[-1].generate_complete()
            self.__expressions__ = self.__expressions__[:-1]
            return suffix
        else:
            return ""

    def length(self):
        return len(self.__expressions__)

    def generate(self):
        for expression in self.__expressions__:
            yield expression.generate()

    def generate_complete(self):
        generated_content = []
        for expression in self.__expressions__:
            generated_content.append(expression.generate_complete())
        return "".join(generated_content)


class XegerExpression(object):
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
        self.__max_random__ = max_random
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
                    self.__random_pattern__ = False
                    try:
                        self.__constant__ = int("".join(mult))
                    except:
                        raise XegerError("Multiplier must be a number")
                    return
                else:
                    raise XegerError("Illegal end of multiplier pattern")
            elif c in ['*', '+', '?']:
                if started:
                    raise XegerError("Error in multiplier pattern")
                else:
                    self.__random_pattern__ = True
                    if c == '+':
                        self.__random__ = FastRandom(1, self.__max_random__)
                    elif c == '*':
                        self.__random__ = FastRandom(0, self.__max_random__)
                    else:
                        self.__random__ = FastRandom(0, 1)
                    return
            else:
                if started:
                    mult.append(c)
                else:
                    break

        if started:
            raise XegerError("Incomplete multiplier")
        else:
            self.__random_pattern__ = False
            self.__constant__ = 1

    def generate(self):
        if not self.random:
            return self.__constant__
        else:
            return self.__random__.rand()


class XegerSequence(object):
    """
    Simple generator, just returns the sequence on each call to generate
    """
    def __init__(self, character_list):
        self.sequence = "".join(character_list)

    def generate(self):
        return self.sequence


class XegerSet(object):
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
                    self.__random__ = FastRandom(0, len(self.__set__) - 1)
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

    def generate(self):
        return self.__set__[self.__random__.rand()]


