"""
Complexity classifier for issues.

This module provides a classifier that categorizes issues into:
- trivial: zero logic decisions, pure mechanical operations
- bounded: clear scope, finite known steps
- open-ended: scope unclear, multiple decisions, may need decomposition

The classifier is orthogonal to risk: a low-risk task can still be bounded or open-ended.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
import re


class ComplexityClass(str, Enum):
    """Complexity classes for issues."""
    TRIVIAL = "trivial"
    BOUNDED = "bounded"
    OPEN_ENDED = "open-ended"


@dataclass
class ComplexityClassification:
    """Result of complexity classification."""
    complexity_class: ComplexityClass
    rationale: str
    confidence: str  # "high", "medium", "low"
    signals: List[str]  # Specific signals that influenced the classification


# Patterns that indicate trivial complexity
TRIVIAL_PATTERNS = {
    # Pure mechanical refactors
    "rename": r"\brename\b",
    "rename_function": r"\brename\s+\w+\s+(to|=>)\s+\w+",
    "rename_variable": r"\brename\s+\w+\s+(to|=>)\s+\w+",
    "rename_class": r"\brename\s+\w+\s+(to|=>)\s+\w+",
    
    # Import changes
    "add_import": r"\badd\s+import\b",
    "remove_import": r"\bremove\s+import\b|remove\s+unused\s+import",
    "update_import": r"\bupdate\s+import\b",
    "from_import": r"\bfrom\s+\w+\s+import\s+",
    
    # Format/lint fixes
    "format_code": r"\b(format\s+code|run\s+(black|white|ruff))\b",
    "fix_lint": r"\bfix\s+lint\b",
    "pep8": r"\bpep8\b",
    "fix_style": r"\bstyle\s+fix\b",
    "whitespace": r"\bwhitespace\b",
    "indentation": r"\bindentation\b",
    
    # Find-and-replace
    "replace_all": r"\breplace\s+all\b",
    "find_replace": r"\bfind\s+and\s+replace\b",
    "search_replace": r"\bsearch\s+and\s+replace\b",
    
    # Simple doc/comment updates
    "update_doc": r"\bupdate\s+(doc|docstring|documentation)\b",
    "fix_typo": r"\bfix\s+typo\b",
    "add_docstring": r"\badd\s+docstring\b",
    
    # Simple migration patterns (deprecation warnings)
    "migrate_deprecated": r"\bmigrate\s+.*\s+deprecated\b",
    "replace_deprecated": r"\breplace\s+deprecated\b",
}

# Patterns that indicate bounded complexity
BOUNDED_PATTERNS = {
    # Feature additions with clear scope
    "add_feature": r"\badd\b",
    "implement_function": r"\bimplement\b.*\bfunction\b",
    "implement_method": r"\bimplement\s+(?:a\s+)?method\b",
    "add_test": r"\badd\b.*\btests?\b",
    "add_endpoint": r"\badd\s+(?:api\s+)?endpoint\b",
    
    # Clear bug fixes with known steps
    "fix_bug": r"\bfix\b",
    "fix_issue": r"\bfix\s+issue\b",
    "fix_error": r"\bfix\s+error\b",
    
    # Config changes
    "update_config": r"\bupdate\s+config\b",
    "add_config": r"\badd\s+config\b",
    
    # Simple refactors (with some logic decisions)
    "extract_function": r"\bextract\b[\s\S]*\bfunction\b",
    "inline_function": r"\binline\s+function\b",
    "simplify": r"\bsimplify\b",
}

# Patterns that indicate open-ended complexity
OPEN_ENDED_PATTERNS = {
    # Ambiguous scope (negative lookahead to avoid conflicts)
    "improve": r"\b(improve|improving)\b",
    "optimize": r"\b(optimize|optimization)\b",
    "enhance": r"\benhance\b(?!\s+(error|security))",
    # "refactor" is in both, handled by priority order
    "refactor_vague": r"\brefactor\b(?!.*(extract|inline|simplify|rename))",
    
    # Architectural changes
    "architectur": r"\barchitectur\b",
    "redesign": r"\bredesign\b",
    "restructure": r"\brestructure\b",
    "reorganize": r"\breorganize\b",
    
    # Strategic decisions
    "decide": r"\bdecide\b",
    "choose": r"\bchoose\b",
    "evaluate": r"\bevaluate\b",
    "investigat": r"\binvestigat\w*\b",
    
    # Multiple components
    "multiple": r"\bmultiple\b",
    "several": r"\bseveral\b",
    "various": r"\bvarious\b",
    
    # Integration work
    "integrate": r"\bintegrate\b",
    "connect": r"\bconnect\b",
    "bridge": r"\bbridge\b",
    
    # Unclear deliverables
    "support": r"\bsupport\b",
    "handle": r"\bhandle\b",
    "manage": r"\bmanage\b",
}

# Complexity floor keywords (strongest signal for trivial)
COMPLEXITY_FLOOR_KEYWORDS = [
    "deprecat",
    "utcnow",
]


def _text_matches_patterns(text: str, patterns: Dict[str, str]) -> List[str]:
    """Check if text matches any of the given patterns.
    
    Returns list of matched pattern names.
    """
    matched = []
    text_lower = text.lower()
    
    for pattern_name, pattern in patterns.items():
        if re.search(pattern, text_lower, re.IGNORECASE):
            matched.append(pattern_name)
    
    return matched


def _check_fast_path_eligibility(issue_body: str, issue_title: str) -> tuple[bool, str]:
    """
    Check if an issue meets fast-path eligibility requirements.
    
    Fast-path requires:
    - Low risk (no destructive, secret, billing, access, downtime, release, production action)
    - Locally bounded and reversible
    - Immediate acceptance check available
    - No dependency, ambiguity, parallelism, or independent human approval required
    
    Returns:
        (is_eligible, reason)
    """
    text = f"{issue_title} {issue_body}".lower()
    
    # Check for high-risk indicators (specific phrases, not broad keywords)
    high_risk_phrases = [
        "deploy to production", "production deploy", "push to production",
        "delete database", "drop table", "truncate table",
        "security vulnerability", "auth bypass", "payment processing",
        "database migration", "schema migration", "force push",
        "release to production", "production release",
        "delete file", "remove file",
    ]
    
    for phrase in high_risk_phrases:
        if phrase in text:
            return False, f"Contains high-risk phrase: '{phrase}'"
    
    # Check for ambiguity or multiple actions
    ambiguity_keywords = [
        "consider", "maybe", "possibly", "think about", "explore",
        "and also", "also consider", "in addition to", "plus", "as well as",
        "multiple files", "several files", "various files",
    ]
    
    for keyword in ambiguity_keywords:
        if keyword in text:
            return False, f"Contains ambiguity indicator: '{keyword}'"
    
    # Check for dependency on external resources or actions
    dependency_keywords = [
        "wait for", "after", "once", "when", "until", "depends on",
        "blocked by", "requires", "needs", "prerequisite",
        "database",
    ]
    
    for keyword in dependency_keywords:
        if keyword in text:
            return False, f"Contains dependency indicator: '{keyword}'"
    
    return True, "Meets fast-path eligibility criteria"


def classify_complexity(
    issue_title: str,
    issue_body: str,
    issue_labels: Optional[List[str]] = None,
) -> ComplexityClassification:
    """
    Classify an issue's complexity.
    
    Args:
        issue_title: The issue title.
        issue_body: The issue body/description.
        issue_labels: Optional list of issue labels/tags.
    
    Returns:
        ComplexityClassification with complexity class, rationale, confidence, and signals.
    """
    # Combine text for analysis
    full_text = f"{issue_title}\n{issue_body}"
    if issue_labels:
        full_text += f"\n{ ' '.join(issue_labels) }"
    
    # Check for complexity floor keywords (strongest signal)
    floor_matches = []
    for keyword in COMPLEXITY_FLOOR_KEYWORDS:
        if keyword in full_text.lower():
            floor_matches.append(keyword)
    
    # Check for trivial patterns
    trivial_matches = _text_matches_patterns(full_text, TRIVIAL_PATTERNS)
    
    # Check for bounded patterns
    bounded_matches = _text_matches_patterns(full_text, BOUNDED_PATTERNS)
    
    # Check for open-ended patterns
    open_ended_matches = _text_matches_patterns(full_text, OPEN_ENDED_PATTERNS)
    
    # Build signals list
    signals = []
    signals.extend([f"floor: {m}" for m in floor_matches])
    signals.extend([f"trivial: {m}" for m in trivial_matches])
    signals.extend([f"bounded: {m}" for m in bounded_matches])
    signals.extend([f"open-ended: {m}" for m in open_ended_matches])
    
    # Classification logic (priority: floor > open-ended > trivial > bounded)
    if floor_matches and not open_ended_matches:
        # Complexity floor keyword + no open-ended signals -> check fast-path eligibility
        is_eligible, eligibility_reason = _check_fast_path_eligibility(issue_body, issue_title)
        if is_eligible:
            return ComplexityClassification(
                complexity_class=ComplexityClass.TRIVIAL,
                rationale=f"Matches complexity floor: {', '.join(floor_matches)}. {eligibility_reason}",
                confidence="high",
                signals=signals,
            )
        else:
            # Matches complexity floor but fails eligibility -> bounded
            return ComplexityClassification(
                complexity_class=ComplexityClass.BOUNDED,
                rationale=f"Matches complexity floor ({', '.join(floor_matches)}) but fails fast-path eligibility: {eligibility_reason}",
                confidence="medium",
                signals=signals,
            )
    
    if open_ended_matches:
        # Any open-ended pattern -> open-ended
        return ComplexityClassification(
            complexity_class=ComplexityClass.OPEN_ENDED,
            rationale=f"Open-ended scope: {', '.join(open_ended_matches)}",
            confidence="high",
            signals=signals,
        )
    
    if trivial_matches and not open_ended_matches:
        # Trivial patterns without open-ended -> check eligibility
        is_eligible, eligibility_reason = _check_fast_path_eligibility(issue_body, issue_title)
        if is_eligible:
            return ComplexityClassification(
                complexity_class=ComplexityClass.TRIVIAL,
                rationale=f"Pure mechanical refactor: {', '.join(trivial_matches)}. {eligibility_reason}",
                confidence="high",
                signals=signals,
            )
        else:
            # Trivial patterns but fails eligibility -> bounded
            return ComplexityClassification(
                complexity_class=ComplexityClass.BOUNDED,
                rationale=f"Mechanical refactor ({', '.join(trivial_matches)}) but fails fast-path eligibility: {eligibility_reason}",
                confidence="medium",
                signals=signals,
            )
    
    if bounded_matches:
        # Bounded patterns without open-ended or trivial -> bounded
        return ComplexityClassification(
            complexity_class=ComplexityClass.BOUNDED,
            rationale=f"Clear scope with finite steps: {', '.join(bounded_matches)}",
            confidence="medium",
            signals=signals,
        )
    
    # Default to open-ended when unclear
    return ComplexityClassification(
        complexity_class=ComplexityClass.OPEN_ENDED,
        rationale="Unclear scope: default to open-ended for safety",
        confidence="low",
        signals=signals,
    )


def is_trivial_issue(issue_title: str, issue_body: str, issue_labels: Optional[List[str]] = None) -> bool:
    """
    Convenience function: check if an issue is trivial.
    
    Args:
        issue_title: The issue title.
        issue_body: The issue body/description.
        issue_labels: Optional list of issue labels/tags.
    
    Returns:
        True if the issue is classified as trivial.
    """
    classification = classify_complexity(issue_title, issue_body, issue_labels)
    return classification.complexity_class == ComplexityClass.TRIVIAL


def route_issue(
    issue_title: str,
    issue_body: str,
    issue_labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Route an issue to the appropriate execution path.
    
    Args:
        issue_title: The issue title.
        issue_body: The issue body/description.
        issue_labels: Optional list of issue labels/tags.
    
    Returns:
        Dict with routing decision and classification details.
    """
    classification = classify_complexity(issue_title, issue_body, issue_labels)
    
    route = {
        "complexity_class": classification.complexity_class.value,
        "rationale": classification.rationale,
        "confidence": classification.confidence,
        "signals": classification.signals,
    }
    
    if classification.complexity_class == ComplexityClass.TRIVIAL:
        route["execution_path"] = "direct"
        route["description"] = "Execute directly with condensed contract, bypassing full AOS lifecycle"
    elif classification.complexity_class == ComplexityClass.BOUNDED:
        route["execution_path"] = "contract_execute_review"
        route["description"] = "Run through contract→execute→review pipeline"
    else:  # OPEN_ENDED
        route["execution_path"] = "full_lifecycle"
        route["description"] = "Run full lifecycle (AOS) including planning stage"
    
    return route