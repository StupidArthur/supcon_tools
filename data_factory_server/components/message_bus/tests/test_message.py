"""
测试消息格式
"""
import json
import time
import pytest
from components.message_bus.message import Message, MessageType


class TestMessage:
    """测试 Message 类"""
    
    def test_message_creation(self):
        """测试消息创建"""
        msg = Message(
            service_name="test_service",
            action="test_action",
            payload={"key": "value"}
        )
        
        assert msg.service_name == "test_service"
        assert msg.action == "test_action"
        assert msg.payload == {"key": "value"}
        assert msg.message_type == MessageType.REQUEST
        assert msg.request_id is None
        assert msg.message_id is not None
        assert msg.timestamp > 0
    
    def test_message_to_json(self):
        """测试消息序列化"""
        msg = Message(
            service_name="test_service",
            action="test_action",
            payload={"key": "value"}
        )
        
        json_str = msg.to_json()
        assert isinstance(json_str, str)
        
        data = json.loads(json_str)
        assert data["service_name"] == "test_service"
        assert data["action"] == "test_action"
        assert data["payload"] == {"key": "value"}
        assert data["message_type"] == "request"
    
    def test_message_from_json(self):
        """测试消息反序列化"""
        json_str = json.dumps({
            "message_id": "test-id",
            "message_type": "request",
            "service_name": "test_service",
            "action": "test_action",
            "payload": {"key": "value"},
            "request_id": None,
            "timestamp": time.time(),
            "ttl": 60
        })
        
        msg = Message.from_json(json_str)
        
        assert msg.message_id == "test-id"
        assert msg.message_type == MessageType.REQUEST
        assert msg.service_name == "test_service"
        assert msg.action == "test_action"
        assert msg.payload == {"key": "value"}
    
    def test_message_round_trip(self):
        """测试消息序列化-反序列化往返"""
        original = Message(
            service_name="test_service",
            action="test_action",
            payload={"key": "value", "nested": {"a": 1, "b": 2}},
            message_type=MessageType.EVENT
        )
        
        json_str = original.to_json()
        restored = Message.from_json(json_str)
        
        assert restored.service_name == original.service_name
        assert restored.action == original.action
        assert restored.payload == original.payload
        assert restored.message_type == original.message_type
    
    def test_create_response(self):
        """测试创建响应消息"""
        request = Message(
            service_name="test_service",
            action="test_action",
            payload={"key": "value"}
        )
        
        response = request.create_response({"result": "success"})
        
        assert response.message_type == MessageType.RESPONSE
        assert response.request_id == request.message_id
        assert response.service_name == request.service_name
        assert response.action == request.action
        assert response.payload["status"] == "ok"
        assert response.payload["data"] == {"result": "success"}
    
    def test_create_error_response(self):
        """测试创建错误响应"""
        request = Message(
            service_name="test_service",
            action="test_action",
            payload={}
        )
        
        response = request.create_error_response("Test error")
        
        assert response.message_type == MessageType.RESPONSE
        assert response.request_id == request.message_id
        assert response.payload["status"] == "error"
        assert response.payload["error"] == "Test error"
    
    def test_different_message_types(self):
        """测试不同的消息类型"""
        types = [
            MessageType.REQUEST,
            MessageType.RESPONSE,
            MessageType.COMMAND,
            MessageType.EVENT
        ]
        
        for msg_type in types:
            msg = Message(
                message_type=msg_type,
                service_name="test",
                action="test"
            )
            assert msg.message_type == msg_type
            
            json_str = msg.to_json()
            restored = Message.from_json(json_str)
            assert restored.message_type == msg_type
