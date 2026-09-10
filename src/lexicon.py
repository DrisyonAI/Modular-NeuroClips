"""
Domain Pronunciation & Phonetic Lexicon Engine.
Maps enterprise acronyms, Indian banking/FinTech jargon, and domain terms
into phonetically accurate speech strings and SSML substitution tags.
"""
import re
from typing import Dict

DEFAULT_FINTECH_LEXICON: Dict[str, str] = {
    # Indian & Global Banking / FinTech
    r"\bKYC\b": "K-Y-C",
    r"\be-?KYC\b": "E-K-Y-C",
    r"\bUPI\b": "U-P-I",
    r"\bRBI\b": "R-B-I",
    r"\bNBFC\b": "N-B-F-C",
    r"\bSEBI\b": "SEB-ee",
    r"\bNEFT\b": "NEFT",
    r"\bRTGS\b": "R-T-G-S",
    r"\bIMPS\b": "IMPS",
    r"\bNPCI\b": "N-P-C-I",
    r"\bEMI\b": "E-M-I",
    r"\bCIBIL\b": "SIB-il",
    r"\bNACH\b": "N-A-C-H",
    r"\bAML\b": "A-M-L",
    r"\bSLA\b": "S-L-A",
    r"\bAPI\b": "A-P-I",
    r"\bSaaS\b": "Sass",
    r"\bFinTech\b": "Fin-tech",
    r"\bRegTech\b": "Reg-tech",
    r"\bGovTech\b": "Gov-tech",
    r"\bAadhaar\b": "Aad-haar",
    r"\bPMLA\b": "P-M-L-A",
    r"\bGST\b": "G-S-T",
    r"\bGSTN\b": "G-S-T-N",
    r"\bPOS\b": "P-O-S",
}

class LexiconEngine:
    """Applies phonetic substitutions to guarantee consistent pronunciation across TTS engines."""

    def __init__(self, custom_lexicon: Dict[str, str] = None):
        self.lexicon = {**DEFAULT_FINTECH_LEXICON, **(custom_lexicon or {})}

    def apply_lexicon(self, text: str) -> str:
        """Substitutes acronyms and difficult domain words with phonetic respellings."""
        result = text
        for pattern, replacement in self.lexicon.items():
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result
