"""Private contact input; saved contact details never prove ownership."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    accepted_recovery: StrictBool = False
    phone_number: str = Field(min_length=9, max_length=20)
    lightning_address: str | None = Field(default=None, max_length=254)

    @field_validator("phone_number")
    @classmethod
    def phone(cls, value):
        import re

        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
            raise ValueError("Use your country code, for example +254700000000")
        return value

    @field_validator("lightning_address")
    @classmethod
    def address(cls, value):
        import re

        if not value:
            return None
        if not re.fullmatch(
            r"[A-Za-z0-9._+-]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}",
            value,
        ):
            raise ValueError("Use a Lightning address such as name@blink.sv")
        local, host = value.rsplit("@", 1)
        if ".." in host:
            raise ValueError("Check the Lightning address")
        return local + "@" + host.lower()
