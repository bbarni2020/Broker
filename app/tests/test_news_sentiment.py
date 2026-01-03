import pytest

from app.services.news_sentiment import NewsSentimentEvaluator, NewsSentimentResult


@pytest.fixture
def evaluator():
    return NewsSentimentEvaluator()


def test_no_signals_passes(evaluator):
    search_signals = {
        "total_results": 0,
        "matched_categories": [],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("AAPL", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "low"
    assert result.total_mentions == 0
    assert len(result.signals_detected) == 0


def test_single_negative_signal_medium_risk(evaluator):
    search_signals = {
        "total_results": 5,
        "matched_categories": ["lawsuits"],
        "earnings": False,
        "lawsuits": True,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("TSLA", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "medium"
    assert "lawsuits" in result.rejection_reason
    assert result.total_mentions == 5


def test_multiple_negative_signals_fails(evaluator):
    evaluator_strict = NewsSentimentEvaluator(max_negative_signals=2)
    
    search_signals = {
        "total_results": 10,
        "matched_categories": ["lawsuits"],
        "earnings": False,
        "lawsuits": True,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator_strict.evaluate("NFLX", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "medium"


def test_earnings_with_high_volume_medium_risk(evaluator):
    search_signals = {
        "total_results": 25,
        "matched_categories": ["earnings"],
        "earnings": True,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("MSFT", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "medium"
    assert "earnings" in result.rejection_reason


def test_excessive_news_volume(evaluator):
    search_signals = {
        "total_results": 60,
        "matched_categories": ["unusual"],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": True,
    }
    
    result = evaluator.evaluate("GME", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "medium"
    assert "excessive" in result.rejection_reason.lower()


def test_fda_event_neutral_signal(evaluator):
    search_signals = {
        "total_results": 8,
        "matched_categories": ["fda"],
        "earnings": False,
        "lawsuits": False,
        "fda": True,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("PFE", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "low"


def test_macro_event_neutral(evaluator):
    search_signals = {
        "total_results": 12,
        "matched_categories": ["macro"],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": True,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("SPY", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "low"


def test_sentiment_score_calculation_no_news(evaluator):
    search_signals = {
        "total_results": 0,
        "matched_categories": [],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("AAPL", search_signals)
    
    assert result.sentiment_score == 0.5


def test_sentiment_score_with_negative_signals(evaluator):
    search_signals = {
        "total_results": 10,
        "matched_categories": ["lawsuits"],
        "earnings": False,
        "lawsuits": True,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("XYZ", search_signals)
    
    assert result.sentiment_score < 0.5


def test_sentiment_score_high_volume_penalty(evaluator):
    search_signals_low = {
        "total_results": 5,
        "matched_categories": [],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    search_signals_high = {
        "total_results": 55,
        "matched_categories": [],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result_low = evaluator.evaluate("ABC", search_signals_low)
    result_high = evaluator.evaluate("ABC", search_signals_high)
    
    assert result_high.sentiment_score < result_low.sentiment_score


def test_unusual_activity_detected(evaluator):
    search_signals = {
        "total_results": 15,
        "matched_categories": ["unusual"],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": True,
    }
    
    result = evaluator.evaluate("DWAC", search_signals)
    
    assert "unusual" in result.signals_detected
    assert result.passed is True


def test_mixed_signals_neutral_and_negative(evaluator):
    search_signals = {
        "total_results": 18,
        "matched_categories": ["earnings", "lawsuits"],
        "earnings": True,
        "lawsuits": True,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("TWTR", search_signals)
    
    assert result.passed is True
    assert result.risk_level == "medium"
    assert len(result.signals_detected) == 2


def test_custom_thresholds():
    evaluator = NewsSentimentEvaluator(
        max_negative_signals=1,
        min_confidence_override=0.9,
    )
    
    search_signals = {
        "total_results": 8,
        "matched_categories": ["lawsuits"],
        "earnings": False,
        "lawsuits": True,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("TEST", search_signals)
    
    assert result.passed is False
    assert result.risk_level == "high"


def test_result_immutability():
    evaluator = NewsSentimentEvaluator()
    search_signals = {
        "total_results": 5,
        "matched_categories": [],
        "earnings": False,
        "lawsuits": False,
        "fda": False,
        "macro": False,
        "unusual_mentions": False,
    }
    
    result = evaluator.evaluate("AAPL", search_signals)
    
    with pytest.raises(AttributeError):
        result.passed = False
