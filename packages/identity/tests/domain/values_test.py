import pytest
from identity.domain.models.values import Email, Password


class TestEmail:
    def test_normalizes_value(self) -> None:
        email = Email("  User.Name+tag@Example.COM ")

        assert email.value == "user.name+tag@example.com"

    @pytest.mark.parametrize("value", ["", "no-at-sign", "a@b", "a b@example.com", "a@@example.com"])
    def test_rejects_invalid_values(self, value: str) -> None:
        with pytest.raises(ValueError, match="Enter a valid email address"):
            Email(value)

    def test_rejects_values_longer_than_maximum_length(self) -> None:
        value = f"{'a' * 309}@example.com"

        with pytest.raises(ValueError, match="Enter a valid email address"):
            Email(value)

    def test_from_trusted_skips_validation_and_preserves_value(self) -> None:
        email = Email.from_trusted("not an email")

        assert email.value == "not an email"

    def test_is_immutable(self) -> None:
        email = Email("user@example.com")

        with pytest.raises(AttributeError):
            setattr(email, "value", "other@example.com")


class TestPassword:
    def test_accepts_minimum_and_maximum_lengths(self) -> None:
        assert Password("x" * Password.MIN_LEN).value == "x" * Password.MIN_LEN
        assert Password("x" * Password.MAX_LEN).value == "x" * Password.MAX_LEN

    def test_rejects_password_shorter_than_minimum_length(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            Password("x" * (Password.MIN_LEN - 1))

    def test_rejects_password_longer_than_maximum_length(self) -> None:
        with pytest.raises(ValueError, match="at most"):
            Password("x" * (Password.MAX_LEN + 1))
