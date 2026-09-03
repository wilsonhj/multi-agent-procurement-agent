"""H.2 - conformance of the canonicaliser the audit hash is computed over.

**Why a conformance suite exists at all.** D-13 (specs/001-procurement-agent/
clarifications.md) chose a library over a hand-rolled near-JCS on the argument
that conformance becomes somebody else's problem - but that argument only holds
*once you have checked it*. Nothing about depending on a package named `rfc8785`
establishes that it implements RFC 8785, and a canonicaliser that is subtly
wrong is the worst failure mode C4 has: chains that verify locally and fail
under any conformant verifier, silently, until an outside auditor looks.

So the vectors below are transcribed from **RFC 8785 itself**, not from the
library's own test suite - a library's tests cannot vouch for the library. Each
one names its section.

**This file is all-ASCII, deliberately, and that costs it a helper.** Its
subject is byte-level string handling, so a vector that depends on a non-ASCII
character or a backslash surviving an editor, a patch tool or a terminal is a
vector that can silently stop testing what it claims to. `_u` below writes the
RFC's `uXXXX` escapes from their hex digits, and section 3.2.4's expected output
is kept as the RFC's own hexadecimal dump. Nothing here rests on this file's own
escaping being transcribed correctly.

The two `test_a_hand_rolled_*` cases are different in kind. They do not test
`rfc8785`; they pin D-13's *[V] verified* claim that `json.dumps(sort_keys=True)`
is not a substitute, so "do not hand-roll this" stays a measured fact rather
than a remembered one.
"""

from __future__ import annotations

import json
import struct

import pytest
import rfc8785

from procurement_agent.audit import CanonicalisationError, canonical_text, canonicalise

#: One backslash, written as its code point. See the module docstring: every
#: vector in this file is JSON *source*, and JSON source is mostly backslashes.
_BS = chr(92)


def _u(hex4: str) -> str:
    """One JSON escape, from the RFC's own four hex digits.

    Takes the digits as text rather than as an int so a row here can be diffed
    against the RFC character for character, including the RFC's mixed case -
    JSON hex digits are case-insensitive, and reproducing the case keeps the
    transcription checkable by eye.
    """
    return f"{_BS}u{hex4}"


# --- RFC 8785 section 3.2.2 / 3.2.3 / 3.2.4: the worked example -----------------

#: The string value from the RFC's section 3.2.2 input, escape by escape: the
#: euro sign, a dollar, U+000F, a newline, A, an apostrophe, an escaped B, an
#: escaped quote, an escaped backslash, a doubled backslash, a quote written
#: as an escape, and the optional solidus escape. It exercises a non-ASCII
#: character, two control characters, a redundantly escaped letter, and three
#: different ways of writing a backslash.
RFC_3_2_2_STRING = (
    _u("20ac")
    + "$"
    + _u("000F")
    + _u("000a")
    + "A'"
    + _u("0042")
    + _u("0022")
    + _u("005c")
    + _BS
    + _BS
    + _BS
    + '"'
    + _BS
    + "/"
)

#: The RFC's parsed input, section 3.2.2, kept as its JSON *source* text rather
#: than as a Python literal. The point of the example is what a JSON parser does
#: with tolerant input - `1E30`, `4.50`, the escaped `B` - so re-expressing it
#: as Python objects would discard the half of the vector being tested.
RFC_3_2_2_INPUT = (
    "{"
    '"numbers": [333333333.33333329, 1E30, 4.50,'
    " 2e-3, 0.000000000000000000000000001],"
    f' "string": "{RFC_3_2_2_STRING}",'
    ' "literals": [null, true, false]'
    "}"
)

#: Section 3.2.4's expected bytes, as the RFC prints them.
RFC_3_2_4_EXPECTED_HEX = (
    "7b 22 6c 69 74 65 72 61 6c 73 22 3a 5b 6e 75 6c 6c 2c 74 72"
    "75 65 2c 66 61 6c 73 65 5d 2c 22 6e 75 6d 62 65 72 73 22 3a"
    "5b 33 33 33 33 33 33 33 33 33 2e 33 33 33 33 33 33 33 2c 31"
    "65 2b 33 30 2c 34 2e 35 2c 30 2e 30 30 32 2c 31 65 2d 32 37"
    "5d 2c 22 73 74 72 69 6e 67 22 3a 22 e2 82 ac 24 5c 75 30 30"
    "30 66 5c 6e 41 27 42 5c 22 5c 5c 5c 5c 5c 22 2f 22 7d"
)


def test_a_rfc_8785_section_3_2_4_byte_vector() -> None:
    """The RFC's own end-to-end example, compared byte for byte.

    Covers all four transformation steps at once - whitespace removal (3.2.1),
    ECMAScript number and string serialisation (3.2.2), UTF-16 property sorting
    (3.2.3) and UTF-8 generation (3.2.4).
    """
    expected = bytes.fromhex(RFC_3_2_4_EXPECTED_HEX.replace(" ", ""))
    assert canonicalise(json.loads(RFC_3_2_2_INPUT)) == expected


def test_a_the_wrapper_is_byte_identical_to_the_library() -> None:
    """`canonicalise` must add nothing.

    Stated as its own test so the vector above is unambiguously a statement
    about `rfc8785`, which is what D-13 asked to be checked, and not about a
    wrapper that might be quietly compensating for it.
    """
    parsed = json.loads(RFC_3_2_2_INPUT)
    assert canonicalise(parsed) == rfc8785.dumps(parsed)


def test_a_canonical_text_is_the_same_bytes_decoded() -> None:
    """`payload_canonical` is a `text` column, so the str form is load-bearing.

    RFC 8785 section 3.2.4 makes UTF-8 part of the specification, so decoding is
    the only lossless way to reach a `str`, and the column therefore round-trips
    the digest input exactly.
    """
    parsed = json.loads(RFC_3_2_2_INPUT)
    assert canonical_text(parsed).encode("utf-8") == canonicalise(parsed)


# --- RFC 8785 section 3.2.3: the property-sorting vector ------------------------

#: The RFC's sorting test data. The emoji key is written as its two UTF-16 code
#: units rather than as one character, which is what the sort actually compares.
RFC_3_2_3_SORT_INPUT = (
    "{"
    f'"{_u("20ac")}":"Euro Sign",'
    f'"{_BS}r":"Carriage Return",'
    f'"{_u("fb33")}":"Hebrew Letter Dalet With Dagesh",'
    '"1":"One",'
    f'"{_u("d83d")}{_u("de00")}":"Emoji: Grinning Face",'
    f'"{_u("0080")}":"Control",'
    f'"{_u("00f6")}":"Latin Small Letter O With Diaeresis"'
    "}"
)

#: "Expected argument order after sorting property strings", RFC 8785 section
#: 3.2.3. Given as the *values*, which is how the RFC prints it - and which
#: happens to make the assertion readable.
RFC_3_2_3_EXPECTED_ORDER = [
    "Carriage Return",
    "One",
    "Control",
    "Latin Small Letter O With Diaeresis",
    "Euro Sign",
    "Emoji: Grinning Face",
    "Hebrew Letter Dalet With Dagesh",
]


def test_a_rfc_8785_section_3_2_3_sorting_vector() -> None:
    """Sorting is by UTF-16 code unit, not by code point.

    U+1F600 sorts *before* U+FB33 because its first UTF-16 code unit is the high
    surrogate 0xD83D, which is numerically below 0xFB33 - while by code point
    0x1F600 is far above it. This single vector is what separates JCS from every
    "sorted keys" JSON encoder.
    """
    canonical = json.loads(canonical_text(json.loads(RFC_3_2_3_SORT_INPUT)))
    assert list(canonical.values()) == RFC_3_2_3_EXPECTED_ORDER


# --- RFC 8785 Appendix B: number serialisation samples --------------------------

#: Appendix B Table 1, keyed by the IEEE 754 bit pattern exactly as the RFC
#: prints it, so a row here can be diffed against the RFC by eye. `None` marks
#: the two rows whose "JSON Representation" cell is empty: note (3), "values out
#: of range are not permitted in JSON".
RFC_APPENDIX_B = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("7fffffffffffffff", None),
    ("7ff0000000000000", None),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
]


@pytest.mark.parametrize(("ieee754", "expected"), RFC_APPENDIX_B)
def test_a_rfc_8785_appendix_b_number_samples(ieee754: str, expected: str | None) -> None:
    """Every row of Appendix B Table 1, including its edge cases.

    Reconstructing the double from its bit pattern rather than from a decimal
    literal is what makes the adjacent rows meaningful: `44b52d02c7e14af5` and
    `44b52d02c7e14af6` differ by one unit in the last place and must serialise
    differently, which no decimal transcription could be trusted to preserve.
    """
    value = struct.unpack(">d", bytes.fromhex(ieee754))[0]
    if expected is None:
        with pytest.raises(CanonicalisationError):
            canonicalise(value)
        return
    assert canonical_text(value) == expected


# --- the domain edges C4 has to fail loudly at ---------------------------------


def test_a_an_integer_beyond_the_safe_double_range_is_refused() -> None:
    """`seq` is a `bigint`, and JCS numbers are doubles.

    A value above 2**53-1 cannot round-trip through an ECMAScript number, so a
    conformant canonicaliser has to refuse it rather than round it. Unreachable
    in practice - nine quadrillion events on one document - but if it were *not*
    refused the result would be a digest no other implementation reproduces,
    which is the outcome D-13 exists to prevent. This asserts that the loud
    direction is the one taken.
    """
    with pytest.raises(CanonicalisationError):
        canonicalise({"seq": 2**53})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_floats_are_refused(value: float) -> None:
    """RFC 8785 section 3.2.2.3: out-of-range values are not permitted in JSON.

    `json.dumps` emits bare `NaN` and `Infinity` by default, which is valid
    JavaScript and invalid JSON - a payload carrying one would produce a
    `payload_canonical` that the generated `payload_canonical::jsonb` column
    then rejects at INSERT, turning a canonicalisation bug into a confusing
    constraint error one layer down. Refusing here keeps the error where the
    cause is.
    """
    with pytest.raises(CanonicalisationError):
        canonicalise({"value": value})


# --- D-13's "do not hand-roll this", kept measured -----------------------------


def test_a_hand_rolled_sorted_keys_json_disagrees_on_key_order() -> None:
    """D-13, [V]: JCS sorts by UTF-16 code unit, Python's `sorted` by code point.

    The divergence is neither hypothetical nor confined to exotic input - any
    key above the BMP reorders against any key in U+E000..U+FFFF, so one emoji
    key is enough to make a hand-rolled encoder produce a different digest.
    """
    hebrew, emoji = chr(0xFB33), chr(0x1F600)
    obj = {hebrew: 1, emoji: 2}
    assert list(json.loads(canonical_text(obj))) == [emoji, hebrew]
    assert list(json.loads(json.dumps(obj, sort_keys=True))) == [hebrew, emoji]


def test_a_hand_rolled_sorted_keys_json_disagrees_on_numbers() -> None:
    """D-13, [V]: JCS emits ECMAScript shortest-round-trip, Python emits `repr`.

    `10.0` and `10` are one JCS number and two Python ones. This is also the
    exact reason D-14 does *not* use JCS for the workbook projection, where the
    int/float distinction is data the store genuinely carries - the two
    contracts want opposite things, which is why both encoders exist.
    """
    assert canonical_text({"n": 10.0}) == '{"n":10}'
    assert json.dumps({"n": 10.0}, sort_keys=True, separators=(",", ":")) == '{"n":10.0}'
