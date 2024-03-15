import logging
from datetime import datetime, date
from typing import Optional
import re

from bs4 import Tag

from amazonorders import constants
from amazonorders.entity.parsable import Parsable
from amazonorders.entity.seller import Seller

logger = logging.getLogger(__name__)


# FIELD_TRANSACTION_REGEX = r"\s*(?P<date>\w+\s\d{1,2},\s\d{4})\s+-\s+(?P<source>[^:]+)\:\s*\$(?P<amount>[0-9\.\-]+)\s*"
ITEMS_SHIPPED_REGEX = r"Items shipped\:\s*(?P<date>\w+\s\d{1,2},\s\d{4})\s+-\s+(?P<source>[^:]+)\:\s*\$(?P<amount>[0-9\.\-]+)\s*"
REFUND_REGEX = r"Refund\:\s*Completed\s+(?P<date>\w+\s\d{1,2},\s\d{4})\s+-\s+\$(?P<amount>[0-9\.\-]+)\s*"

class Transaction(Parsable):
    """
    A Transaction in an Amazon :class:`~amazonorders.entity.order.Order`.
    """

    def __init__(self, parsed: Tag) -> None:
        super().__init__(parsed)

        # print(f"Transaction text: [[{parsed.getText('\n', True)}]]")
        # details_str = self.simple_parse(constants.FIELD_TRANSACTION_DETAILS_SELECTOR, required=True)
        details_str = parsed.getText('\n', True)
        # print("Transactions raw: [[[" + details_str + "]]]")

        self._details_match = re.match(ITEMS_SHIPPED_REGEX, details_str, re.MULTILINE)
        if (self._details_match):
            self.type = "purchase"
            self.purpose = "Items shipped"
        else:
            self._details_match = re.match(REFUND_REGEX, details_str, re.MULTILINE)
            if (self._details_match):
                self.type = "refund"
                self.purpose = "Refund"
            else:
                # logger.error("Unable to parse order transactions")
                raise Exception(f"Unable to parse order transaction [[{details_str}]]")

        #: The Transaction date.
        self.date: Optional[date] = self.safe_parse(self._parse_date)
        #: The Transaction source.
        self.source: str = self.safe_parse(self._parse_source)
        #: The Transaction amount.
        self.amount: Optional[float] = self.safe_parse(self._parse_amount)
        #: The Transaction purpose.
        # self.purpose: Optional[str] = self.safe_parse(self._parse_purpose)

    def __repr__(self) -> str:
        return f"<Transaction: [{self.type}] {self.date} - \"{self.source}\": {self.amount}>"

    def __str__(self) -> str:  # pragma: no cover
        return f"Transaction: [{self.type}] {self.date} - {self.source}: {self.amount}"

    def __lt__(self, other):
        return self.date < other.date

    def _parse_date(self) -> Optional[date]:
        # value = None
        value = datetime.strptime(self._details_match.group("date"), "%B %d, %Y").date()

        return value

    def _parse_source(self) -> Optional[str]:
        value = None
        if "source" in self._details_match.groupdict():
            value = self._details_match.group("source")

        return value

    def _parse_amount(self) -> Optional[float]:
        # value = None
        value = float(self._details_match.group("amount"))

        return value

    # def _parse_purpose(self) -> Optional[str]:
    #     value = self.simple_parse(constants.FIELD_TRANSACTION_PURPOSE_SELECTOR).strip()
    #     if (value[-1] == ":"):
    #         value = value[:-1]
    #     return value
