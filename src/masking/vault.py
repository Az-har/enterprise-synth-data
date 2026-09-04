"""
Referential Vault for Format-Preserving Pseudonymization.
Guarantees 1:1 Bijective Mapping and Cross-Table Referential Consistency.
"""
from typing import Dict, Any, Callable, List, Optional
import hashlib


class ReferentialVault:
    """
    Session mapping vault.
    Guarantees that:
    1. If 'orig_val' is encountered anywhere in any table/column of the same domain,
       it is consistently replaced by the exact same 'masked_val'.
    2. No two distinct 'orig_val' will ever map to the same 'masked_val' (strict 1:1 bijection).
    3. User-supplied custom lists are prioritized without breaking cardinality.
    """

    def __init__(self, salt: str = "enterprise_synth_salt_2026"):
        self.salt = salt
        # domain -> {orig_val: masked_val}
        self._forward_map: Dict[str, Dict[str, str]] = {}
        # domain -> {masked_val: orig_val} (ensures uniqueness)
        self._reverse_map: Dict[str, Dict[str, str]] = {}
        # domain -> list of user-provided values
        self._custom_pools: Dict[str, List[str]] = {}
        # domain -> index of next user-provided value to use
        self._custom_indices: Dict[str, int] = {}

    def set_custom_pool(self, domain: str, values: List[str]):
        """Registers a user-supplied replacement list for a domain."""
        domain_key = domain.strip().lower()
        cleaned_values = [v.strip() for v in values if v and v.strip()]
        self._custom_pools[domain_key] = cleaned_values
        self._custom_indices[domain_key] = 0

    def get_or_create(
        self,
        domain: str,
        original_value: Any,
        generator_func: Callable[[Any], str]
    ) -> str:
        """
        Retrieves existing pseudonym for 'original_value' or generates a unique new one.
        Guarantees 1:1 bijection (cardinality preservation).
        """
        if original_value is None:
            return ""

        orig_str = str(original_value).strip()
        if not orig_str:
            return ""

        domain_key = domain.strip().lower()
        if domain_key not in self._forward_map:
            self._forward_map[domain_key] = {}
            self._reverse_map[domain_key] = {}

        # 1. Return existing mapping if already assigned
        if orig_str in self._forward_map[domain_key]:
            return self._forward_map[domain_key][orig_str]

        # 2. Try using user-provided custom value first
        masked_val = self._try_get_custom_val(domain_key, orig_str)

        # 3. If no custom value available, generate using generator_func with collision resolution
        if not masked_val:
            masked_val = self._generate_unique_val(domain_key, orig_str, generator_func)

        # 4. Save bijective mapping
        self._forward_map[domain_key][orig_str] = masked_val
        self._reverse_map[domain_key][masked_val] = orig_str
        return masked_val

    def _try_get_custom_val(self, domain_key: str, orig_str: str) -> Optional[str]:
        """Attempts to pull next unused custom value from user list."""
        if domain_key in self._custom_pools:
            pool = self._custom_pools[domain_key]
            idx = self._custom_indices.get(domain_key, 0)
            while idx < len(pool):
                candidate = pool[idx]
                self._custom_indices[domain_key] = idx + 1
                if candidate not in self._reverse_map[domain_key]:
                    return candidate
                idx += 1
            # If user pool is exhausted, we don't duplicate; fallback to generator
        return None

    def _generate_unique_val(
        self,
        domain_key: str,
        orig_str: str,
        generator_func: Callable[[Any], str]
    ) -> str:
        """Calls generator_func and ensures result is globally unique in this domain."""
        max_attempts = 100
        for attempt in range(max_attempts):
            candidate = generator_func(orig_str)
            if candidate and candidate not in self._reverse_map[domain_key]:
                return candidate

        # If collision occurs repeatedly, append deterministic suffix
        base_hash = hashlib.sha256(f"{self.salt}_{orig_str}".encode()).hexdigest()[:6]
        candidate = f"{generator_func(orig_str)} #{base_hash}"
        return candidate

    def get_stats(self, domain: str) -> Dict[str, Any]:
        """Returns mapping statistics and cardinality checks for a domain."""
        domain_key = domain.strip().lower()
        forward_count = len(self._forward_map.get(domain_key, {}))
        reverse_count = len(self._reverse_map.get(domain_key, {}))
        return {
            "domain": domain_key,
            "unique_original_values": forward_count,
            "unique_masked_values": reverse_count,
            "cardinality_preserved": forward_count == reverse_count,
            "custom_pool_used": self._custom_indices.get(domain_key, 0),
            "custom_pool_total": len(self._custom_pools.get(domain_key, []))
        }

    def reset(self):
        """Clears all session mappings."""
        self._forward_map.clear()
        self._reverse_map.clear()
        self._custom_pools.clear()
        self._custom_indices.clear()
