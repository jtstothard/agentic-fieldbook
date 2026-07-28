"""
Tests for complexity classifier (#48).

Tests cover:
- Mechanical refactor issues → trivial
- Features with clear scope → bounded
- Ambiguous/architectural issues → open-ended
- Fast-path eligibility checks
- Complexity floor keyword detection
"""

import pytest

from agentic_fieldbook.complexity_classifier import (
    ComplexityClass,
    ComplexityClassification,
    classify_complexity,
    is_trivial_issue,
    route_issue,
)


class TestTrivialComplexityClassification:
    """Test classification of trivial mechanical refactors."""

    def test_mechanical_refactor_datetime_deprecation(self):
        """A datetime.utcnow() migration is classified as trivial."""
        # pricerecon#55 example from dogfood
        title = "Replace datetime.utcnow() with datetime.now(timezone.utc)"
        body = "Replace all 42 occurrences of datetime.utcnow() with datetime.now(timezone.utc). Add timezone import where needed."
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert result.confidence in ("high", "medium")
        assert "trivial" in " ".join(result.signals)
        assert "utcnow" in " ".join(result.signals) or "deprecat" in " ".join(result.signals).lower()

    def test_simple_rename_function(self):
        """Renaming a function is trivial."""
        title = "Rename validate_email to is_valid_email"
        body = "Rename the function for consistency with other validation functions."
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "rename" in " ".join(result.signals).lower()

    def test_add_import(self):
        """Adding an import is trivial."""
        title = "Add typing import"
        body = "Add `from typing import Optional` to utils.py"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "import" in " ".join(result.signals).lower()

    def test_fix_typo(self):
        """Fixing a typo is trivial."""
        title = "Fix typo in error message"
        body = "Change ' occured' to ' occurred' in line 42"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "typo" in " ".join(result.signals).lower()

    def test_remove_unused_imports(self):
        """Removing unused imports is trivial."""
        title = "Remove unused imports"
        body = "Clean up unused imports in all modules"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "import" in " ".join(result.signals).lower()

    def test_format_code(self):
        """Formatting code is trivial."""
        title = "Run black formatter"
        body = "Format all Python files with black"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "format" in " ".join(result.signals).lower()


class TestBoundedComplexityClassification:
    """Test classification of bounded tasks with clear scope."""

    def test_add_feature(self):
        """Adding a specific feature is bounded."""
        title = "Add rate limiting endpoint"
        body = "Add a /rate-limit endpoint that returns current usage statistics"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.BOUNDED
        assert "add" in " ".join(result.signals).lower() or "feature" in " ".join(result.signals).lower()

    def test_implement_function(self):
        """Implementing a specific function is bounded."""
        title = "Implement password validation function"
        body = "Add validate_password() that checks length, complexity, and common passwords"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.BOUNDED

    def test_add_tests(self):
        """Adding tests is bounded."""
        title = "Add unit tests for user module"
        body = "Cover all public functions in user.py with unit tests"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.BOUNDED
        assert "test" in " ".join(result.signals).lower()

    def test_fix_specific_bug(self):
        """Fixing a specific bug is bounded."""
        title = "Fix segfault on null pointer"
        body = "Add null check before dereferencing pointer in handle_request()"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.BOUNDED

    def test_extract_function(self):
        """Extracting a function is bounded (requires some logic)."""
        title = "Extract duplicate email logic"
        body = "Move email validation to a shared function used by login and signup"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.BOUNDED


class TestOpenEndedComplexityClassification:
    """Test classification of open-ended/architectural issues."""

    def test_improve_performance(self):
        """'Improve performance' is open-ended."""
        title = "Improve API performance"
        body = "The API is slow. Make it faster."
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.OPEN_ENDED
        assert "improve" in " ".join(result.signals).lower()

    def test_optimize_database(self):
        """'Optimize database' is open-ended."""
        title = "Optimize database queries"
        body = "Queries are taking too long"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.OPEN_ENDED
        assert "optimiz" in " ".join(result.signals).lower()

    def test_refactor_architecture(self):
        """Architectural refactor is open-ended."""
        title = "Refactor authentication system"
        body = "The current auth system is messy. Clean it up."
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.OPEN_ENDED
        assert "refactor" in " ".join(result.signals).lower()

    def test_investigate_issue(self):
        """Investigation tasks are open-ended."""
        title = "Investigate memory leak"
        body = "Memory usage keeps growing. Find the leak."
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.OPEN_ENDED
        assert "investigat" in " ".join(result.signals).lower()

    def test_integrate_service(self):
        """Integration work is open-ended."""
        title = "Integrate with payment gateway"
        body = "Connect our system to Stripe"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.OPEN_ENDED
        assert "integrat" in " ".join(result.signals).lower()

    def test_ambiguous_scope(self):
        """Ambiguous tasks are open-ended."""
        title = "Handle errors better"
        body = "Error handling needs improvement"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.OPEN_ENDED


class TestFastPathEligibility:
    """Test fast-path eligibility checks for trivial tasks."""

    def test_trivial_with_high_risk_keyword(self):
        """Trivial pattern with high-risk keyword should not be fast-path eligible."""
        title = "Replace datetime.utcnow() in production config"
        body = "Update production.py with timezone-aware datetime"
        
        result = classify_complexity(title, body)
        
        # Should be trivial (production alone is not high-risk, only specific phrases)
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "utcnow" in " ".join(result.signals).lower()

    def test_trivial_with_dependency(self):
        """Trivial pattern with dependency should not be fast-path eligible."""
        title = "Replace datetime.utcnow()"
        body = "Wait for v2.0 migration, then replace all occurrences"
        
        result = classify_complexity(title, body)
        
        # Should be bounded due to dependency
        assert result.complexity_class == ComplexityClass.BOUNDED
        assert "dependency" in result.rationale.lower() or "wait" in result.rationale.lower()

    def test_trivial_with_ambiguity(self):
        """Trivial pattern with ambiguity should not be fast-path eligible."""
        title = "Replace datetime.utcnow()"
        body = "Maybe also consider updating other deprecated APIs while we're at it"
        
        result = classify_complexity(title, body)
        
        # Should be bounded due to ambiguity
        assert result.complexity_class == ComplexityClass.BOUNDED
        assert "ambiguit" in result.rationale.lower() or "also" in result.rationale.lower()

    def test_trivial_with_database_keyword(self):
        """Database-related tasks should not be fast-path eligible."""
        title = "Replace deprecated database call"
        body = "Update all database.query() calls to use the new API"
        
        result = classify_complexity(title, body)
        
        # Should be bounded due to database keyword
        assert result.complexity_class == ComplexityClass.BOUNDED


class TestComplexityFloorKeywords:
    """Test complexity floor keyword detection."""

    def test_utcnow_keyword(self):
        """utcnow keyword signals trivial complexity floor."""
        title = "Fix datetime issues"
        body = "Replace utcnow with now(timezone.utc) throughout the codebase"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "utcnow" in " ".join(result.signals).lower()

    def test_deprecated_keyword(self):
        """deprecat keyword signals trivial complexity floor."""
        title = "Update deprecated API"
        body = "Replace all deprecated function calls with their replacements"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert "deprecat" in " ".join(result.signals).lower()

    def test_multiple_floor_keywords(self):
        """Multiple floor keywords reinforce trivial classification."""
        title = "Migrate deprecated datetime usage"
        body = "Replace all utcnow() with now(timezone.utc)"
        
        result = classify_complexity(title, body)
        
        assert result.complexity_class == ComplexityClass.TRIVIAL
        assert result.confidence == "high"


class TestIsTrivialIssueConvenienceFunction:
    """Test the is_trivial_issue convenience function."""

    def test_returns_true_for_trivial(self):
        """Returns True for trivial issues."""
        result = is_trivial_issue(
            "Fix typo",
            "Change ' occured' to ' occurred'"
        )
        assert result is True

    def test_returns_false_for_bounded(self):
        """Returns False for bounded issues."""
        result = is_trivial_issue(
            "Add rate limiting",
            "Add a /rate-limit endpoint"
        )
        assert result is False

    def test_returns_false_for_open_ended(self):
        """Returns False for open-ended issues."""
        result = is_trivial_issue(
            "Improve performance",
            "Make the API faster"
        )
        assert result is False

    def test_with_labels(self):
        """Works with labels."""
        result = is_trivial_issue(
            "Fix typo",
            "Change typo",
            issue_labels=["bug", "documentation"]
        )
        assert result is True


class TestRouteIssue:
    """Test the route_issue function."""

    def test_routes_trivial_to_direct(self):
        """Trivial tasks route to direct execution."""
        result = route_issue(
            "Fix typo",
            "Change ' occured' to ' occurred'"
        )
        
        assert result["complexity_class"] == "trivial"
        assert result["execution_path"] == "direct"
        assert "condensed contract" in result["description"]
        assert "bypassing" in result["description"].lower()

    def test_routes_bounded_to_contract_execute_review(self):
        """Bounded tasks route to contract→execute→review pipeline."""
        result = route_issue(
            "Add rate limiting",
            "Add a /rate-limit endpoint"
        )
        
        assert result["complexity_class"] == "bounded"
        assert result["execution_path"] == "contract_execute_review"
        assert "contract→execute→review" in result["description"]

    def test_routes_open_ended_to_full_lifecycle(self):
        """Open-ended tasks route to full lifecycle."""
        result = route_issue(
            "Improve performance",
            "Make the API faster"
        )
        
        assert result["complexity_class"] == "open-ended"
        assert result["execution_path"] == "full_lifecycle"
        assert "full lifecycle" in result["description"].lower()
        assert "planning" in result["description"].lower()

    def test_includes_classification_details(self):
        """Route result includes full classification details."""
        result = route_issue(
            "Fix typo",
            "Change ' occured' to ' occurred'"
        )
        
        assert "rationale" in result
        assert "confidence" in result
        assert "signals" in result
        assert isinstance(result["signals"], list)
        assert len(result["signals"]) > 0


class TestComplexityClassificationDataclass:
    """Test ComplexityClassification dataclass."""

    def test_classification_structure(self):
        """Classification has required fields."""
        classification = ComplexityClassification(
            complexity_class=ComplexityClass.TRIVIAL,
            rationale="Test rationale",
            confidence="high",
            signals=["signal1", "signal2"]
        )
        
        assert classification.complexity_class == ComplexityClass.TRIVIAL
        assert classification.rationale == "Test rationale"
        assert classification.confidence == "high"
        assert len(classification.signals) == 2

    def test_complexity_class_enum(self):
        """ComplexityClass enum has correct values."""
        assert ComplexityClass.TRIVIAL.value == "trivial"
        assert ComplexityClass.BOUNDED.value == "bounded"
        assert ComplexityClass.OPEN_ENDED.value == "open-ended"