from agents.base import BaseAgent
from core.bus import bus
from core.message import Message, AgentID, MessageType, Priority
from risk.gate import risk_gate


class RiskGateAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            AgentID.RISK_GATE,
            "You are the Risk Gate. You enforce deterministic risk rules only."
        )

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ORDER_REQUEST:
            await self._validate_order(message)

        elif message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "update_account":
                risk_gate.update_account(
                    equity=float(message.payload.get("equity", 0)),
                    balance=float(message.payload.get("balance", 0)),
                    open_positions=int(message.payload.get("open_positions", 0)),
                    daily_pnl=float(message.payload.get("daily_pnl", 0)),
                )
            elif command == "activate_kill_switch":
                if message.sender in (AgentID.HUMAN, AgentID.CRO):
                    risk_gate.activate_kill_switch(
                        reason=message.payload.get("reason", "manual")
                    )
            elif command == "deactivate_kill_switch":
                if message.sender == AgentID.HUMAN:
                    risk_gate.deactivate_kill_switch()

    async def _validate_order(self, message: Message):
        try:
            order = risk_gate.order_from_payload(message.payload)
        except (KeyError, ValueError) as e:
            await self.send(
                recipient=message.sender,
                msg_type=MessageType.ORDER_REJECTED,
                payload={
                    "reason": f"malformed_order:{str(e)}",
                    "original_msg_id": message.id,
                },
                priority=Priority.HIGH,
                correlation_id=message.id,
            )
            return

        decision = risk_gate.validate_order(order)
        response_msg = risk_gate.build_validated_message(message, decision, order)
        await bus.publish(response_msg)
