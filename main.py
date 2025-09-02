from agents import (
    Agent, Runner,
    function_tool, ModelSettings
)
from my_config.config import model

ORDER_DB = {
    "123": "📦 Your order #123 has been shipped and is on the way!",
    "456": "✅ Your order #456 was delivered yesterday.",
    "789": "🕒 Your order #789 is still being processed."
}


# --- Tool: fetch order status ---
@function_tool()
def get_order_status(order_id: str) -> str:
    """
    Check the status of an order by ID.
    """
    try:
        return ORDER_DB.get(order_id, "❌ Order not found")
    except Exception as err:
        return f"⚠️ Unable to fetch order status: {err}"


# --- Simple Guardrail (manual logic, no decorator needed) ---
def no_negative_input(user_input: str) -> str | None:
    """Block offensive/negative inputs and trigger handoff."""
    negatives = ["stupid", "idiot", "useless", "hate"]
    if any(word in user_input.lower() for word in negatives):
        return "⚠️ Please keep the conversation respectful."
    return None


# --- Define Agents ---
BotAgent = Agent(
    name="BotAgent",
    model=model,
    instructions=(
        "You are a helpful customer support bot. "
        "Answer FAQs, fetch order status using tools. "
        "If the query is too complex or the user is upset, escalate to HumanAgent."
    ),
    tools=[get_order_status],
    handoffs=[],  # handoffs handle dynamically
    model_settings=ModelSettings(tool_choice="auto")
)

HumanAgent = Agent(
    name="HumanAgent",
    model=model,
    instructions="You are a human customer support representative. Handle escalated queries with empathy."
)


# --- Hybrid handler ---
def handle_customer_query(query: str):
    print(f"\n👉 Customer: {query}")

    # 1. Guardrail check
    guardrail_msg = no_negative_input(query)
    if guardrail_msg:
        print(f"🤖 Bot (guardrail): {guardrail_msg}")
        print("🔀 Escalating to HumanAgent (due to negativity)...")
        human_runner = Runner.run_sync(HumanAgent, query)
        print(f"🙋 Human: {human_runner.final_output}")
        return

    # 2. Bot tries first
    runner = Runner.run_sync(BotAgent, query)

    # 3. Escalation conditions
    if "complex" in query.lower() or "not found" in str(runner.final_output).lower():
        print("🔀 Escalating to HumanAgent (custom rule)...")
        human_runner = Runner.run_sync(HumanAgent, query)
        print(f"🙋 Human: {human_runner.final_output}")
    else:
        # 4. Normal case
        print(f"🤖 Bot: {runner.final_output}")


# --- Test hybrid system ---
def main():
    test_queries = [
        "Hi, what is your name?",
        "Can you check order 123?",
        "What about order 999?",        
        "You are stupid !",             
        "I have a very complex problem with my account settings."
    ]

    for q in test_queries:
        handle_customer_query(q)


if __name__ == "__main__":
    main()