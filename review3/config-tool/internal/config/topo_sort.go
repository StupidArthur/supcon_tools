package config

import "fmt"

func topologicalSort(nodes []BlockNode, edges []Connection) ([]BlockNode, error) {
	if len(nodes) == 0 {
		return nodes, nil
	}

	deps := make(map[string]map[string]bool)
	dependents := make(map[string]map[string]bool)
	nodeMap := make(map[string]BlockNode)

	for _, node := range nodes {
		deps[node.ID] = make(map[string]bool)
		dependents[node.ID] = make(map[string]bool)
		nodeMap[node.ID] = node
	}

	for _, edge := range edges {
		if edge.Source == edge.Target {
			continue
		}
		if _, ok := deps[edge.Target]; !ok {
			continue
		}
		deps[edge.Target][edge.Source] = true
		if _, ok := dependents[edge.Source]; !ok {
			dependents[edge.Source] = make(map[string]bool)
		}
		dependents[edge.Source][edge.Target] = true
	}

	inDegree := make(map[string]int)
	for id, depSet := range deps {
		inDegree[id] = len(depSet)
	}

	var queue []string
	for _, node := range nodes {
		if inDegree[node.ID] == 0 {
			queue = append(queue, node.ID)
		}
	}

	var sorted []string
	sortedSet := make(map[string]bool)

	for len(queue) > 0 {
		id := queue[0]
		queue = queue[1:]
		sorted = append(sorted, id)
		sortedSet[id] = true
		for dependent := range dependents[id] {
			inDegree[dependent]--
			if inDegree[dependent] == 0 {
				queue = append(queue, dependent)
			}
		}
	}

	if len(sorted) < len(nodes) {
		var breakNodes []string
		for _, node := range nodes {
			if !sortedSet[node.ID] && node.ExecuteFirst {
				breakNodes = append(breakNodes, node.ID)
			}
		}

		if len(breakNodes) == 0 {
			var cycleNodes []string
			for _, node := range nodes {
				if !sortedSet[node.ID] {
					cycleNodes = append(cycleNodes, node.Name)
				}
			}
			return nil, fmt.Errorf("检测到依赖环，环中无 execute_first 节点: %v", cycleNodes)
		}

		for _, bn := range breakNodes {
			inDegree[bn] = 0
			queue = append(queue, bn)
		}

		for len(queue) > 0 {
			id := queue[0]
			queue = queue[1:]
			if sortedSet[id] {
				continue
			}
			sorted = append(sorted, id)
			sortedSet[id] = true
			for dependent := range dependents[id] {
				inDegree[dependent]--
				if inDegree[dependent] == 0 {
					queue = append(queue, dependent)
				}
			}
		}

		if len(sorted) < len(nodes) {
			var remaining []string
			for _, node := range nodes {
				if !sortedSet[node.ID] {
					remaining = append(remaining, node.Name)
				}
			}
			return nil, fmt.Errorf("依赖环无法解开: %v", remaining)
		}
	}

	result := make([]BlockNode, 0, len(sorted))
	for _, id := range sorted {
		result = append(result, nodeMap[id])
	}
	return result, nil
}
