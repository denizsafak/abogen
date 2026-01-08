import pytest
from abogen.kokoro_text_normalization import (
    _normalize_grouped_numbers,
    ApostropheConfig,
)


@pytest.fixture
def cfg():
    return ApostropheConfig(convert_numbers=True, year_pronunciation_mode="american")


def normalize(text, config):
    return _normalize_grouped_numbers(text, config)


class TestDateNormalization:

    def test_standard_years(self, cfg):
        # 1990 -> nineteen hundred ninety
        assert "nineteen hundred ninety" in normalize("In 1990, the web was born.", cfg)
        # 1066 -> ten sixty-six
        assert "ten sixty-six" in normalize("The battle was in 1066.", cfg)
        # 2023 -> twenty twenty-three
        assert "twenty twenty-three" in normalize("It is currently 2023.", cfg)
        # 1905 -> nineteen hundred oh five
        assert "nineteen hundred oh five" in normalize(
            "In 1905, Einstein published.", cfg
        )

    def test_future_years(self, cfg):
        # 3400 -> thirty-four hundred
        assert "thirty-four hundred" in normalize("In the year 3400, we fly.", cfg)
        # 2500 -> twenty-five hundred
        assert "twenty-five hundred" in normalize("The year 2500 is far off.", cfg)

    def test_years_with_markers(self, cfg):
        # 1021 BC -> ten twenty-one
        assert "ten twenty-one" in normalize("It happened in 1021 BC.", cfg)
        # 4000 BCE -> forty hundred (or four thousand?)
        # _format_year_like logic:
        # if value % 1000 == 0: return "X thousand"
        # 4000 -> four thousand.
        # Let's check 4001 -> forty oh one
        assert "forty oh one" in normalize("Ancient times 4001 BCE.", cfg)

    def test_addresses_explicit(self, cfg):
        # "address" keyword present -> should NOT be year
        # 1925 -> one thousand nine hundred twenty-five (default num2words)
        # or "one nine two five" if num2words isn't doing year stuff.
        # num2words(1925) -> "one thousand, nine hundred and twenty-five"
        res = normalize("My address is 1925 Main St.", cfg)
        assert "nineteen twenty-five" not in res
        assert "one thousand" in res or "nineteen hundred" in res

        res = normalize("Please send it to the address: 3400 North Blvd.", cfg)
        assert "thirty-four hundred" not in res  # Should not be year style
        assert "three thousand" in res or "thirty-four hundred" in res
        # Wait, "thirty-four hundred" IS how you say 3400 in num2words sometimes?
        # num2words(3400) -> "three thousand, four hundred" usually.
        # Let's verify what "thirty-four hundred" implies.
        # If it's a year: "thirty-four hundred".
        # If it's a number: "three thousand four hundred".
        assert "three thousand" in res

    def test_address_with_year_marker_edge_case(self, cfg):
        # "address" is present, BUT "BC" is also present. Should be year.
        res = normalize("The address was found in 1021 BC ruins.", cfg)
        assert "ten twenty-one" in res

    def test_ambiguous_numbers(self, cfg):
        # Just a number, no "address", no markers. Should default to year if 4 digits 1000-9999
        assert "nineteen hundred fifty" in normalize("I have 1950 apples.", cfg)
        # This is a known limitation/feature: it aggressively identifies years.

    def test_specific_user_examples(self, cfg):
        # 1021
        assert "ten twenty-one" in normalize("1021", cfg)
        # 1925
        assert "nineteen hundred" in normalize("1925", cfg)
        # 3400
        assert "thirty-four hundred" in normalize("3400", cfg)

    def test_martin_ford_jobless_future_context(self, cfg):
        # Simulating a title or sentence from the book
        # "The Rise of the Robots: Technology and the Threat of a Jobless Future"
        # Maybe it mentions a year like 2015 (pub date) or a future date.

        # "In 2015, Martin Ford wrote..."
        assert "twenty fifteen" in normalize("In 2015, Martin Ford wrote...", cfg)

        # "By 2100, robots will..."
        assert "twenty-one hundred" in normalize("By 2100, robots will...", cfg)

    def test_address_context_window(self, cfg):
        # "address" is far away (> 60 chars). Should be year.
        padding = "x" * 70
        text = f"address {padding} 1999"
        assert "nineteen hundred ninety-nine" in normalize(text, cfg)

        # "address" is close (< 60 chars). Should be number.
        padding = "x" * 10
        text = f"address {padding} 1999"
        res = normalize(text, cfg)
        assert "nineteen hundred ninety-nine" not in res
        assert "one thousand" in res

    def test_2000s(self, cfg):
        # 2000-2009 are usually "two thousand X"
        assert "two thousand one" in normalize("2001", cfg)
        assert "two thousand nine" in normalize("2009", cfg)
        # 2010 -> twenty ten
        assert "twenty ten" in normalize("2010", cfg)

    def test_addresses_plural(self, cfg):
        # "addresses" plural -> should also trigger non-year mode?
        # Currently the code only looks for "address".
        # "The addresses are 1925 and 1926."
        # If it fails to detect "addresses", it will say "nineteen twenty-five".
        # If we want it to be "one thousand...", we need to update the regex.
        res = normalize("The addresses are 1925 and 1926.", cfg)
        # Expectation: should probably be numbers, not years.
        assert "nineteen twenty-five" not in res
