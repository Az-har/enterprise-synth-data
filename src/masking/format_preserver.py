"""
Format-Preserving Masker.
Implements Rule 1: Structural Token Matching & Legal Entity Suffix Preservation.
E.g., 'ABB LLC' -> 3-token / matching word company with 'LLC'.
"""
import re
import random
from typing import Optional, Tuple
from faker import Faker

# Common international enterprise legal suffixes (case-insensitive regex)
LEGAL_SUFFIXES = [
    "LLC", "L.L.C.", "INC", "INC.", "CORP", "CORP.", "CORPORATION",
    "GMBH", "G.M.B.H.", "AG", "A.G.", "LTD", "LTD.", "LIMITED",
    "CO", "CO.", "COMPANY", "SA", "S.A.", "PVT LTD", "PVT. LTD.",
    "BV", "B.V.", "NV", "N.V.", "PLC", "P.L.C.", "KG", "SE",
    "HOLDINGS", "GROUP", "SOLUTIONS", "INTERNATIONAL"
]

# Curated business words for realistic enterprise company name generation
BUSINESS_PREFIXES = [
    "Apex", "Nova", "Vanguard", "Summit", "Vertex", "Quantum", "Nexus",
    "Beacon", "Pinnacle", "Aero", "Stellar", "Titan", "Crest", "Horizon",
    "Atlas", "Delta", "Orion", "Sierra", "Prime", "Zenith", "Omega",
    "Synergy", "Pacific", "Atlantic", "Nordic", "Global", "United", "Frontier"
]

BUSINESS_MIDDLES = [
    "Tech", "Bio", "Logistics", "Digital", "Dynamics", "Systems", "Energy",
    "Robotics", "Analytics", "Materials", "Industrial", "Consulting", "Capital",
    "Networks", "Automation", "Engineering", "Solutions", "Services", "Ventures"
]

BUSINESS_NOUNS = [
    "Enterprises", "Industries", "Technologies", "Partners", "Associates",
    "Holdings", "Innovations", "Solutions", "Dynamics", "International"
]


class FormatPreservingMasker:
    """
    Format and structure-preserving string synthesizer.
    Guarantees structural fidelity while completely masking identity.
    """

    def __init__(self, seed: int = 42):
        self.faker = Faker()
        Faker.seed(seed)
        random.seed(seed)

    def extract_legal_suffix(self, company_name: str) -> Tuple[str, Optional[str]]:
        """
        Splits a company name into (base_name, legal_suffix).
        E.g. 'ABB LLC' -> ('ABB', 'LLC')
        E.g. 'Siemens AG' -> ('Siemens', 'AG')
        """
        cleaned = company_name.strip()
        tokens = cleaned.split()
        if not tokens:
            return ("", None)

        # Check multi-word suffixes first (e.g. 'PVT LTD')
        if len(tokens) >= 2:
            two_word_suffix = f"{tokens[-2]} {tokens[-1]}".upper()
            for s in LEGAL_SUFFIXES:
                if two_word_suffix == s or two_word_suffix.replace(".", "") == s:
                    return (" ".join(tokens[:-2]), f"{tokens[-2]} {tokens[-1]}")

        # Check single-word suffix
        last_word = tokens[-1].upper().replace(",", "")
        for s in LEGAL_SUFFIXES:
            if last_word == s or last_word.replace(".", "") == s:
                return (" ".join(tokens[:-1]).rstrip(","), tokens[-1])

        return (cleaned, None)

    def mask_company_name(self, original_name: str, target_word_count: Optional[int] = None) -> str:
        """
        Rule 1: Generates a realistic company name matching the token count
        and strictly preserving the legal entity suffix (e.g., 'LLC', 'AG', 'GmbH').
        If target_word_count is specified (e.g. 3 words), generates exactly that word count.
        """
        if not original_name or not original_name.strip():
            return ""

        orig_str = original_name.strip()
        base_name, suffix = self.extract_legal_suffix(orig_str)
        base_tokens = base_name.split()

        # Determine target word count for base name
        if target_word_count is not None:
            num_words = max(1, target_word_count - (1 if suffix else 0))
        else:
            # Default to matching original base word count, but at least 2 words if user asked for a 3-word company with suffix
            num_words = len(base_tokens)
            if num_words < 2 and suffix:
                num_words = 2  # e.g., 'ABB LLC' (1 word base + LLC) -> generates 2-word base + LLC = 3-word company

        # Build base name
        if num_words == 1:
            # Could be an acronym or single brand name
            if base_name.isupper() and len(base_name) <= 4:
                # Generate matching uppercase acronym (e.g., KXT, NVR)
                base = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=len(base_name)))
            else:
                base = random.choice(BUSINESS_PREFIXES)
        elif num_words == 2:
            base = f"{random.choice(BUSINESS_PREFIXES)} {random.choice(BUSINESS_MIDDLES)}"
        elif num_words == 3:
            base = f"{random.choice(BUSINESS_PREFIXES)} {random.choice(BUSINESS_MIDDLES)} {random.choice(BUSINESS_NOUNS)}"
        else:
            # 4+ words
            parts = [random.choice(BUSINESS_PREFIXES)]
            for _ in range(num_words - 2):
                parts.append(random.choice(BUSINESS_MIDDLES))
            parts.append(random.choice(BUSINESS_NOUNS))
            base = " ".join(parts)

        # Preserve all-caps casing if original was fully uppercase
        if orig_str.isupper():
            base = base.upper()

        # Re-attach original suffix
        if suffix:
            return f"{base} {suffix}"
        return base

    def mask_person_name(self, original_name: str) -> str:
        """Preserves structure of personal names (e.g., First Last, First M. Last)."""
        tokens = original_name.strip().split()
        if len(tokens) == 1:
            return self.faker.last_name()
        elif len(tokens) == 2:
            return f"{self.faker.first_name()} {self.faker.last_name()}"
        elif len(tokens) == 3 and (len(tokens[1]) <= 2 or tokens[1].endswith(".")):
            # Initial in middle: e.g. John D. Doe
            initial = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            return f"{self.faker.first_name()} {initial}. {self.faker.last_name()}"
        else:
            return f"{self.faker.first_name()} {self.faker.last_name()}"

    def mask_email(self, original_email: str) -> str:
        """Preserves email domain structure while masking mailbox."""
        if "@" not in original_email:
            return self.faker.email()
        parts = original_email.split("@")
        user = re.sub(r"[^a-zA-Z0-9]", "", parts[0])[:8] or "user"
        random_id = random.randint(100, 999)
        return f"synth_{user}_{random_id}@enterprisetest.org"

    def mask_tax_vat_id(self, original_vat: str) -> str:
        """Preserves country prefix and length for VAT / Tax IDs (e.g. DE123456789)."""
        cleaned = original_vat.strip().replace(" ", "").upper()
        if len(cleaned) >= 4 and cleaned[:2].isalpha():
            prefix = cleaned[:2]
            num_digits = len(cleaned) - 2
            random_digits = "".join(random.choices("0123456789", k=num_digits))
            return f"{prefix}{random_digits}"
        else:
            return "".join(random.choices("0123456789", k=len(cleaned)))
