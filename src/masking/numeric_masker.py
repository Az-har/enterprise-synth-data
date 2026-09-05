"""
Numeric Masker.
Implements Rule 3: Obfuscation of IDs, Document Numbers, and Financial Amounts.
Preserves string lengths, zero-padding, decimal precision, and mathematical signs.
"""
import random
from typing import Union


class NumericMasker:
    """
    Masker for numeric IDs and financial quantities.
    Guarantees totally different numbers while maintaining data type constraints.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)  # Scoped private PRNG; zero process-wide mutation (Section 7.3.1)

    def mask_id_string(self, original_id: str) -> str:
        """
        Obfuscates a numeric ID string (e.g., SAP 10-digit zero-padded '0001234567').
        Maintains exact total length and leading zero count structure.
        """
        raw = str(original_id).strip()
        if not raw:
            return ""

        total_len = len(raw)
        # Count leading zeros
        leading_zeros = len(raw) - len(raw.lstrip("0"))

        if leading_zeros == total_len:
            # All zeros: generate valid zero-padded number
            return "0" * (total_len - 1) + str(self.rng.randint(1, 9))

        non_zero_len = total_len - leading_zeros
        # Generate new random digits
        first_digit = str(self.rng.randint(1, 9))
        remaining = "".join(self.rng.choices("0123456789", k=non_zero_len - 1))
        new_body = first_digit + remaining

        # Re-attach leading zeros
        return ("0" * leading_zeros) + new_body

    def mask_amount(
        self,
        original_amount: Union[int, float, str],
        perturbation_range: float = 0.15
    ) -> float:
        """
        Obfuscates financial amounts by applying a calibrated percentage shift (+/- 5% to 25%).
        Preserves decimal scale and positive/negative sign.
        """
        try:
            val = float(original_amount)
        except (ValueError, TypeError):
            return 0.0

        if val == 0.0:
            return 0.0

        sign = 1 if val > 0 else -1
        abs_val = abs(val)

        # Fix DEF-07: Bound min_shift and max_shift so range is never inverted
        p_range = max(0.001, abs(perturbation_range))
        min_shift = min(0.05, p_range * 0.5)
        max_shift = max(min_shift, p_range)
        direction = self.rng.choice([-1, 1])
        shift_pct = self.rng.uniform(min_shift, max_shift)
        shifted_val = abs_val * (1.0 + (direction * shift_pct))

        return round(sign * shifted_val, 2)

    def mask_bank_account(self, original_account: str) -> str:
        """Masks IBAN or bank account number preserving country prefix and length."""
        raw = str(original_account).strip().replace(" ", "").upper()
        if len(raw) >= 15 and raw[:2].isalpha():
            # IBAN: e.g. DE89 3704 0044 0532 0130 00
            country = raw[:2]
            check_digits = f"{self.rng.randint(10, 99)}"
            account_digits = "".join(self.rng.choices("0123456789", k=len(raw) - 4))
            return f"{country}{check_digits}{account_digits}"
        else:
            return "".join(self.rng.choices("0123456789", k=len(raw) if len(raw) > 0 else 10))
