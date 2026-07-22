// -*- coding: utf-8 -*-
package main

import "testing"

func TestProcessLineMarkers(t *testing.T) {
	var ep string
	var n int
	// 无关行不影响
	if processLine("开始构建节点树", &ep, &n) {
		t.Fatal("无关行不应判定完成")
	}
	if processLine("构建完成", &ep, &n) {
		t.Fatal("无关行不应判定完成")
	}
	// 启动成功行：提取 endpoint，但节点数未到，未完成
	if processLine("服务启动成功 opc.tcp://0.0.0.0:18955/ua_mocker/", &ep, &n) {
		t.Fatal("节点数未获取时不应判定完成")
	}
	if ep != "opc.tcp://0.0.0.0:18955/ua_mocker/" {
		t.Errorf("endpoint 解析错误: %q", ep)
	}
	// 节点数量行：齐备，完成
	if !processLine("节点数量: 26", &ep, &n) {
		t.Fatal("两标记齐备应判定完成")
	}
	if n != 26 {
		t.Errorf("节点数应为 26，实际 %d", n)
	}
}

func TestProcessLineIgnoresBadCount(t *testing.T) {
	var ep string
	var n int
	processLine("服务启动成功 opc.tcp://x", &ep, &n)
	// 非数字节点数不采纳
	if processLine("节点数量: abc", &ep, &n) {
		t.Fatal("非法节点数不应判定完成")
	}
}

func TestTailBufferKeepsLastN(t *testing.T) {
	tb := &tailBuffer{n: 2}
	tb.add("a")
	tb.add("b")
	tb.add("c")
	if got := tb.String(); got != "b\nc" {
		t.Errorf("应只保留最后 2 行，实际 %q", got)
	}
}

func TestTailBufferEmpty(t *testing.T) {
	tb := &tailBuffer{n: 3}
	if got := tb.String(); got != "" {
		t.Errorf("空缓冲应为空串，实际 %q", got)
	}
}
