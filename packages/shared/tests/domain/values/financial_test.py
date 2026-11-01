import pytest
from shared.domain.values.financial import Pix, PixKeyType


@pytest.mark.parametrize(
    ("key", "key_type"),
    [
        ("52998224725", PixKeyType.CPF),
        ("12ABC34501DE35", PixKeyType.CNPJ),
        ("+5511998765432", PixKeyType.PHONE),
        ("pix@bcb.gov.br", PixKeyType.EMAIL),
        ("123e4567-e89b-12d3-a456-426655440000", PixKeyType.EVP),
    ],
)
def test_accepts_pix_key_for_type(key: str, key_type: PixKeyType):
    pix = Pix(key=key, type_=key_type)

    assert pix.key == key
    assert pix.type is key_type


@pytest.mark.parametrize(
    ("key", "key_type"),
    [
        ("5299822472", PixKeyType.CPF),
        ("1234567890123", PixKeyType.CNPJ),
        ("5511998765432", PixKeyType.PHONE),
        ("PIX@BCB.GOV.BR", PixKeyType.EMAIL),
        ("123E4567-E89B-12D3-A456-426655440000", PixKeyType.EVP),
    ],
)
def test_rejects_pix_key_that_does_not_match_type(key: str, key_type: PixKeyType):
    with pytest.raises(ValueError, match="valid Pix key"):
        Pix(key=key, type_=key_type)


def test_rejects_pix_key_longer_than_dict_limit():
    key = f"{'a' * 66}@example.com"

    with pytest.raises(ValueError, match="valid Pix key"):
        Pix(key=key, type_=PixKeyType.EMAIL)
