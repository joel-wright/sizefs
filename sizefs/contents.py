import random
import logging

DEBUG = True

if DEBUG:
    logging.getLogger().setLevel(logging.DEBUG)


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
    reserved_chars = ['[', ']', '{', '}', '*', '+', '?']

    def __init__(self, size, filler=None, prefix=None,
                 suffix=None, padder=None, max_random=10):
        self.__size__ = size
        self.__end_last_read__ = 0
        self.__logger__ = logging.getLogger()

        if filler == "":
            self.__logger__.error("Empty filler pattern supplied,"
                                  " using default")
            filler = None
        elif padder == "":
            self.__logger__.error("Empty padder pattern supplied,"
                                  " using default")
            padder = None
        elif prefix == "":
            self.__logger__.error("Empty prefix pattern supplied,"
                                  " using default")
            prefix = None
        elif suffix == "":
            self.__logger__.error("Empty suffix pattern supplied,"
                                  " using default")
            suffix = None

        if filler is not None:
            self.__filler__ = Xeger(filler, max_random)
        else:
            self.__filler__ = Xeger("0", max_random)
        self.__filler_gen__ = self.__filler__.generate()

        if padder is not None:
            self.__padder__ = Xeger(padder, max_random)
        else:
            self.__padder__ = Xeger("0", max_random)
        self.__padder_gen__ = self.__padder__.generate()

        if prefix is not None:
            self.__prefix__ = Xeger(prefix, max_random).generate_complete()
            self.__prefix_length__ = len(self.__prefix__)
        else:
            self.__prefix__ = ""
            self.__prefix_length__ = 0

        if suffix is not None:
            self.__suffix__ = Xeger(suffix, max_random).generate_complete()
            self.__suffix_length__ = len(self.__suffix__)
        else:
            self.__suffix__ = ""
            self.__suffix_length__ = 0

        if size < (self.__prefix_length__ + self.__suffix_length__):
            self.__logger__.error("Prefix and suffix combination is longer than"
                                  "the requested size of the file. One or both will"
                                  "be truncated")

    def read(self, start, end):
        """
        Return regex content.

        Only fully supports sequential reading, however, any read with start or
        end range within a specified prefix or suffix pattern will produce
        appropriate output (this is necessary for metadata testing functions).
        """
        if end > self.__size__ - 1:
            self.__logger__.error("Can't read past the end")
            end = self.__size__ - 1

        if start < 0:
            self.__logger__.error("Can't read before the beginning")
            start = 0

        if not start == self.__end_last_read__ + 1:
            # If we're not reading sequentially, get rid of any remainder
            self.remainder = ""

        self.__end_last_read__ = end

        if start < self.__prefix_length__:
            self.remainder = ""
            content = self.__prefix__[start:]
        else:
            content = self.remainder

        chunk_size = end - start

        # This look horrendous
        # TODO: tidy up the read logic
        if end > (self.__size__ - self.__suffix_length__):
            # If we're sufficiently close to the end size of the contents
            # requested, then we need to consider padding and suffix
            last = self.__suffix__[:self.__suffix_length__ +
                                    (end - (self.__size__ - 1))]
            while len(content) < (chunk_size - len(last)):
                more = self.__get_filler__()
                still_required = chunk_size - len(content) - len(last)
                if len(more) > still_required:
                    pad = self.__get_padding__(still_required)
                    content += pad
                else:
                    content += more
            content += last
            return content
        else:
            while len(content) < chunk_size:
                more = self.__get_filler__()
                still_required = chunk_size - len(content)
                if len(more) > still_required:
                    overrun = len(more) - still_required
                    if (end + overrun) > (self.__size__ - 1 -
                                              self.__suffix_length__):
                        final = self.__get_padding__(still_required)
                        self.remainder = self.__get_padding__(overrun)
                    else:
                        if (end + overrun) > self.__size__ - 1:
                            final = self.__get_padding__(still_required)
                        else:
                            self.remainder = more[still_required:]
                            final = more[:still_required]
                    content += final
                else:
                    content += more
            return content

    def __get_padding__(self, size):
        pad = []
        pad_length = 0

        while pad_length < size:
            pad_content = self.__padder__.generate_complete()
            pad.append(pad_content)
            pad_length += len(pad_content)

        return "".join(pad)[:size]

    def __get_filler__(self):
        return self.__filler__.generate_complete()


class Xeger(object):
    """
    Parses a given regex pattern and yields content on demand.

    regex - a string describing the requested pattern
    max_random - a value passed within the generator describing the maximum
                 number of repeats for * or + operators
    """

    def __init__(self, regex, max_random=10):
        self.__pattern__ = XegerPattern(regex, max_random=max_random)

    def generate(self):
        for content in self.__pattern__.generate():
            yield content

    def generate_complete(self):
        generated_content = []
        for pattern_content in self.generate():
            generated_content.append(pattern_content)
        return "".join(generated_content)


class XegerPattern(object):
    """
    Parses a given pattern into a list of XegerExpressions

    This generates a list of top-level expressions that can be used to generate
    the contents of a file.
    """

    def __init__(self, regex, max_random=10):
        self.__max_random__ = max_random
        self.__parse_expressions__(regex)

    def __parse_expressions__(self, regex):
        self.__expressions__ = []
        regex_list = list(regex)
        while regex_list:
            expression = XegerExpression(regex_list, self.__max_random__)
            self.__expressions__.append(expression)

    def length(self):
        return len(self.__expressions__)

    def generate(self):
        for expression in self.__expressions__:
            for ex in expression.generate():
                yield ex

    def generate_complete(self):
        generated_content = []
        for expression in self.__expressions__:
            for expression_content in expression.generate():
                generated_content.append(expression_content)
        return "".join(generated_content)


class XegerExpression(object):
    """
    Parses an Expression from a list of input characters
    """

    def __init__(self, regex_list, max_random=10):
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
                #accum.append(c)
                c = regex.pop(0)
                accum.append(c)
            elif c in ['{', '*', '+', '?']:  # We've reached a multiplier
                if len(accum) == 1:  # just multiply a single character
                    regex.insert(0, c)
                    self.__generator__ = XegerSequence(accum)
                    self.__multiplier__ = XegerMultiplier(regex)
                    self.__is_constant_multiplier__()
                    return
                elif len(accum) > 1:  # only multiply the last character
                    last_c = accum.pop(-1)
                    regex.insert(0, c)
                    regex.insert(0, last_c)
                    self.__generator__ = XegerSequence(accum)
                    self.__constant_multiplier__ = True
                    self.__multiplier__ = 1
                    return
                else:
                    raise XegerError("Multiplier used without expression")
            else:  # just keep collecting boring characters
                accum.append(c)

        if accum:  # If there's anything left in the accumulator, must be chars
            self.__generator__ = XegerSequence(accum)
            self.__constant_multiplier__ = True
            self.__multiplier__ = 1

    def __is_constant_multiplier__(self):
        if not self.__multiplier__.is_random:
            self.__constant_multiplier__ = True
            self.__multiplier__ = self.__multiplier__.value()
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
        content = []

        if self.__constant_multiplier__:
            mult = self.__multiplier__
        else:
            mult = self.__multiplier__.value()

        for x in range(mult):
            content += self.__generator__.generate_complete()

        yield "".join(content)


class XegerMultiplier(object):
    """
    Represents a multiplier
    """

    def __init__(self, regex, max_random=10):
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
                    self.is_random = False
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
                    self.is_random = True
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
                    regex.insert(0, c)
                    break

        if started:
            raise XegerError("Incomplete multiplier")
        else:
            self.is_random = False
            self.__constant__ = 1

    def value(self):
        if self.is_random:
            return self.__random__.rand()
        else:
            return self.__constant__


class XegerSequence(object):
    """
    Simple generator, just returns the sequence on each call to generate
    """

    def __init__(self, character_list):
        self.__sequence__ = "".join(character_list)

    def generate_complete(self):
        return self.__sequence__


class XegerSet(object):
    """
    Set generator, parses an input list for a set and returns a single element
    on each call to generate (generate_complete is identical)
    """

    def __init__(self, regex):
        if DEBUG:
            self.__logger__ = logging.getLogger()
            self.__logger__.debug("Parsing Set from regex: %s" % "".join(regex))
        self.__parse_set__(regex)

    def __parse_set__(self, regex):
        select_list = []
        ch1 = ''

        while regex:
            c = regex.pop(0)
            if c == ']':
                if not ch1 == '':
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
                    # Remove the unneeded character from the last loop
                    select_list.pop(-1)
                    ch2 = regex.pop(0)
                    set_extras = self.__char_range__(ch1, ch2)
                    for extra in set_extras:
                        select_list.append(extra)
            elif c == '\\':  # Escape the next character
                c = regex.pop(0)
                ch1 = c
                select_list.append(c)
            elif c in XegerGen.reserved_chars:
                raise XegerError("Non-escaped special character in set")
            else:
                ch1 = c
                select_list.append(ch1)

        # The range was incomplete because we never reached the closing brace
        raise XegerError("Incomplete set description")

    def __char_range__(self, a, b):
        for c in xrange(ord(a), ord(b) + 1):
            yield chr(c)

    def generate_complete(self):
        return self.__set__[self.__random__.rand()]


