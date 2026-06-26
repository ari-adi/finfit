import datetime
from typing import List, Dict, Any
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("FinFit MCP Server")

# Mock Data
MOCK_SUBSCRIPTION_STATS = {
    "netflix": {
        "category": "Entertainment",
        "usage_score": 85,
        "last_used_days_ago": 1,
        "description": "Premium 4K streaming plan. Shared with family."
    },
    "spotify": {
        "category": "Entertainment",
        "usage_score": 95,
        "last_used_days_ago": 0,
        "description": "Individual Premium music streaming plan."
    },
    "gym": {
        "category": "Health & Fitness",
        "usage_score": 10,
        "last_used_days_ago": 28,
        "description": "All-access membership. Flagged as extremely low usage!"
    },
    "adobe cc": {
        "category": "Productivity",
        "usage_score": 40,
        "last_used_days_ago": 12,
        "description": "Creative Cloud Individual subscription."
    },
    "amazon prime": {
        "category": "Shopping",
        "usage_score": 90,
        "last_used_days_ago": 2,
        "description": "Yearly prime delivery and video streaming membership."
    }
}

@mcp.tool()
def list_mock_subscriptions() -> List[Dict[str, Any]]:
    """List active mock subscriptions with their pricing and cycles."""
    return [
        {"name": "Netflix", "cost": 15.49, "billing_cycle": "monthly", "status": "active"},
        {"name": "Spotify", "cost": 10.99, "billing_cycle": "monthly", "status": "active"},
        {"name": "Gym", "cost": 50.00, "billing_cycle": "monthly", "status": "active"},
        {"name": "Adobe CC", "cost": 54.99, "billing_cycle": "monthly", "status": "active"},
        {"name": "Amazon Prime", "cost": 139.00, "billing_cycle": "yearly", "status": "active"},
    ]

@mcp.tool()
def get_subscription_details(name: str) -> Dict[str, Any]:
    """Retrieve detailed usage statistics and description for a specific subscription.
    
    Args:
        name: The name of the subscription (e.g. Netflix, Spotify, Gym).
    """
    key = name.lower().strip()
    stats = MOCK_SUBSCRIPTION_STATS.get(key)
    if not stats:
        return {"error": f"Subscription '{name}' not found in database."}
    return {
        "name": name,
        **stats
    }

@mcp.tool()
def generate_savings_calculator(monthly_income: float, target_savings_rate: float) -> Dict[str, Any]:
    """Calculate recommended budget categories and projected monthly savings.
    
    Args:
        monthly_income: The user's monthly post-tax income in USD.
        target_savings_rate: The desired savings rate as a percentage (e.g., 20 for 20%).
    """
    if target_savings_rate < 0 or target_savings_rate > 100:
        return {"error": "Savings rate must be between 0 and 100."}
        
    target_savings = monthly_income * (target_savings_rate / 100.0)
    remaining_budget = monthly_income - target_savings
    
    # 50-30-20 rule recommendation adjusted to target rate
    needs_ratio = 50 / 80.0
    wants_ratio = 30 / 80.0
    
    recommended_needs = remaining_budget * needs_ratio
    recommended_wants = remaining_budget * wants_ratio
    
    return {
        "monthly_income": monthly_income,
        "target_savings_rate_percent": target_savings_rate,
        "monthly_savings_goal": round(target_savings, 2),
        "total_spending_limit": round(remaining_budget, 2),
        "recommended_needs_limit": round(recommended_needs, 2),
        "recommended_wants_limit": round(recommended_wants, 2),
    }

@mcp.tool()
def estimate_upcoming_bills(days: int = 30) -> List[Dict[str, Any]]:
    """Estimate upcoming bill payments and due dates within the next N days.
    
    Args:
        days: The lookahead window in days (default is 30).
    """
    today = datetime.date.today()
    bills = [
        {"name": "Spotify", "amount": 10.99, "due_date": (today + datetime.timedelta(days=3)).isoformat()},
        {"name": "Netflix", "amount": 15.49, "due_date": (today + datetime.timedelta(days=7)).isoformat()},
        {"name": "Adobe CC", "amount": 54.99, "due_date": (today + datetime.timedelta(days=15)).isoformat()},
        {"name": "Gym", "amount": 50.00, "due_date": (today + datetime.timedelta(days=20)).isoformat()},
        {"name": "Electricity Utility", "amount": 85.20, "due_date": (today + datetime.timedelta(days=25)).isoformat()},
    ]
    
    filtered_bills = []
    for bill in bills:
        due = datetime.date.fromisoformat(bill["due_date"])
        if (due - today).days <= days:
            filtered_bills.append(bill)
            
    return filtered_bills

if __name__ == "__main__":
    mcp.run()
