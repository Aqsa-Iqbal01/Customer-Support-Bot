import asyncio
from typing import Optional, Dict, Any
from my_config.config import model

try:
    from agents import Agent, Runner, function_tool, ItemHelpers
    from agents.guardrail import guardrail
   
except Exception:
    
    class Agent:  
        def __init__(self, name: str, instructions: str, model: Optional[str] = None, tools: Optional[list] = None):
            self.name = name
            self.instructions = instructions
            self.model = model
            self.tools = tools or []

    class Runner:  
        def __init__(self, agent: Agent):
            self.agent = agent

        async def run_streamed(self, input: str, *, metadata: Optional[Dict[str, Any]] = None, model_settings: Optional[Dict[str, Any]] = None):
            
            class _Dummy:
                async def stream_events(self):
                    yield type("Evt", (), {"item": type("It", (), {"type": "message", "content": f"(MOCK) {input}"})})
            return _Dummy()

    def function_tool(*dargs, **dkwargs): 
        def deco(fn):
            fn._is_function_tool = True
            fn._tool_kwargs = dkwargs
            return fn
        return deco

    def guardrail(fn):  
        fn._is_guardrail = True
        return fn

    class ItemHelpers:  
        @staticmethod
        def text_message_output(item):
            return getattr(item, "content", "")


FAKE_ORDERS: Dict[str, Dict[str, str]] = {
    "123": {"status": "Shipped", "eta": "2-3 days", "carrier": "FastEx"},
    "456": {"status": "Processing", "eta": "5-7 days", "carrier": "LogiPak"},
    "789": {"status": "Delivered", "eta": "—", "carrier": "FastEx"},
}


def log_event(event_type: str, details: Dict[str, Any]):
    print(f"[LOG] {event_type}: {details}")

@guardrail
def language_guardrail(user_text: str) -> bool:
    """True = allowed, False = blocked"""
    bad_words = ["idiot", "stupid", "nonsense", "curse", "abuse", "fool"]
    text = (user_text or "").lower()
    if any(w in text for w in bad_words):
        return False
    return True


def is_negative_sentiment(user_text: str) -> bool:
    neg_markers = ["refund now", "very bad", "worst", "angry", "nonsense", "wrong", "cancel order"]
    t = (user_text or "").lower()
    return any(m in t for m in neg_markers)


def _is_order_query(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(k in t for k in ["order", "status", "tracking", "track", "order id", "my order id", "my order", "id "])

def _friendly_order_not_found(order_id: str) -> str:
    return (
        f"[INFO] It seems order_id '{order_id}' was not found in our system.\n"
        "Please share the correct order ID (e.g., 123, 456, 789). If the issue persists, I will forward you to a Human Agent."
    )

@function_tool(
    name="get_order_status",
    description="Simulated order status checker",
    is_enabled=lambda query: _is_order_query(query.get("user_text", "")),
    error_function=lambda *args, **kwargs: _friendly_order_not_found(kwargs.get("order_id", "(missing)")),
)
def get_order_status(order_id: str) -> str:

    log_event("tool_invocation", {"tool": "get_order_status", "order_id": order_id})
    data = FAKE_ORDERS.get(order_id)
    if not data:
      
        raise ValueError("ORDER_NOT_FOUND")
    return (
        f"Order {order_id}: Status = {data['status']}, ETA = {data['eta']}, Carrier = {data['carrier']}"
    )

FAQS: Dict[str, str] = {
    "return policy": "Our return policy is 30 days. Item must be unused and with receipt for easy return.",
    "shipping time": "Standard shipping delivers in 3-5 days. Express 1-2 days.",
    "payment methods": "We accept COD, Credit/Debit cards, and bank transfer.",
}

def try_faq_answer(user_text: str) -> Optional[str]:
    text = (user_text or "").lower()
    if "return" in text:
        return FAQS["return policy"]
    if "shipping" in text or "delivery" in text:
        return FAQS["shipping time"]
    if "payment" in text or "card" in text or "cod" in text:
        return FAQS["payment methods"]
    return None

BOT_INSTRUCTIONS = (
    "You are a friendly Customer Support Bot. Assist in English.\n"
    "1) First run guardrails.\n"
    "2) If query is order-related, use get_order_status tool.\n"
    "3) Give direct answers for simple FAQs.\n"
    "4) If complex or negative, handoff to Human Agent.\n"
)

HUMAN_INSTRUCTIONS = (
    "You are a Human Support Agent. Solve issues professionally in English."
)

bot_agent = Agent(
    name="BotAgent",
    instructions=BOT_INSTRUCTIONS,
    model=model, 
    tools=[get_order_status],
)

human_agent = Agent(
    name="HumanAgent",
    instructions=HUMAN_INSTRUCTIONS,
    model=model
)

async def handle_message(user_text: str, customer_id: str) -> None:
  
    if not language_guardrail(user_text):
        print(
            "[WARNING] Please maintain respect in communication. Kindly rephrase your message."
        )
        log_event("guardrail_block", {"text": user_text})
        return
    
    faq = try_faq_answer(user_text)
    order_like = _is_order_query(user_text)

    if is_negative_sentiment(user_text):
        
        log_event("handoff", {"reason": "negative_sentiment", "to": "HumanAgent"})
        await run_with_agent(human_agent, user_text, customer_id, tool_choice="auto")
        return

    if faq and not order_like:
        print(f"[BOT FAQ] {faq}")
        log_event("faq_answered", {"faq": faq})
        return

  
    if order_like:
        order_id = extract_order_id(user_text)
        if not order_id:
            print("[BOT] Please share your order ID (e.g., 123, 456, 789).")
            return
        try:
            result = get_order_status(order_id=order_id) 
            print(f"[BOT ORDER] {result}")
            return
        except Exception:
            
            print(_friendly_order_not_found(order_id))
            return

    
    model_settings = {
        "tool_choice": "auto", 
        "metadata": {"customer_id": customer_id, "channel": "chat"},
    }


    ok = await run_with_agent(bot_agent, user_text, customer_id, **model_settings)

    if not ok:
        log_event("handoff", {"reason": "no_clear_answer", "to": "HumanAgent"})
        await run_with_agent(human_agent, user_text, customer_id, tool_choice="auto")

async def run_with_agent(agent: Agent, user_text: str, customer_id: str, **model_settings):
    print(f"\n--- Message sent to {agent.name} ---")
    print(f"[User-{customer_id}]: {user_text}")

    runner = Runner(agent)
    try:
        result = await runner.run_streamed(
            input=user_text,
            metadata={"customer_id": customer_id},
            model_settings=model_settings or {"tool_choice": "auto"},
        )

        confident = False
        async for event in result.stream_events():
            item = event.item
            itype = getattr(item, "type", "message")

            if itype == "message":
                print(f"[{agent.name}]: {ItemHelpers.text_message_output(item)}")
                confident = True

            elif itype == "tool_call_item":
                log_event("tool_call", {"agent": agent.name, "tool": getattr(item, "name", "unknown")})
            elif itype == "tool_result_item":
                log_event("tool_result", {"agent": agent.name, "result": getattr(item, "output", "")})
            elif itype == "handoff_item":
                log_event("handoff_event", {"from": agent.name, "to": "HumanAgent"})
                confident = False
            elif itype == "error":
                log_event("agent_error", {"agent": agent.name})
                confident = False

        return confident

    except Exception as e:
        log_event("runner_exception", {"agent": agent.name, "error": str(e)})
        return False


def extract_order_id(text: str) -> Optional[str]:
  
    if not text:
        return None
    tokens = text.replace("#", " ").replace(":", " ").split()
    for tok in tokens:
        if tok.isdigit():
            return tok
    for tok in tokens:
        num = "".join(ch for ch in tok if ch.isdigit())
        if num:
            return num
    return None


async def main():
    print("\n===== Smart Customer Support Bot (English) Demo =====\n")
   
    await handle_message("What is the return policy?", customer_id="CUST-1001")
    
    await handle_message("Check my order status, order id is 123.", customer_id="CUST-1002")

    await handle_message("Status for order ID 999?", customer_id="CUST-1003")

    await handle_message("Your service is worst, refund now!", customer_id="CUST-1004")

    await handle_message("Do you provide gift wrapping?", customer_id="CUST-1005")

    await handle_message("You all are nonsense", customer_id="CUST-1006")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
