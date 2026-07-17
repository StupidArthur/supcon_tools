package config

type CanvasState struct {
	Clock  ClockConfig  `json:"clock"`
	Nodes  []BlockNode  `json:"nodes"`
	Edges  []Connection `json:"edges"`
}

type ClockConfig struct {
	Mode      string  `json:"mode"`
	CycleTime float64 `json:"cycleTime"`
}

type Position struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
}

type BlockNode struct {
	ID           string         `json:"id"`
	Name         string         `json:"name"`
	Type         string         `json:"type"`
	Position     Position       `json:"position"`
	Params       map[string]any `json:"params"`
	ExecuteFirst bool           `json:"executeFirst"`
}

type Connection struct {
	ID         string `json:"id"`
	Source     string `json:"source"`
	SourcePort string `json:"sourcePort"`
	Target     string `json:"target"`
	TargetPort string `json:"targetPort"`
}

type ComponentMeta struct {
	Type        string       `json:"type"`
	Category    string       `json:"category"`
	DisplayName string       `json:"displayName"`
	Inputs      []InputPort  `json:"inputs"`
	Outputs     []OutputPort `json:"outputs"`
	Params      []ParamMeta  `json:"params"`
	Doc         string       `json:"doc"`
}

type InputPort struct {
	Name        string `json:"name"`
	Type        string `json:"type"`
	Connectable bool   `json:"connectable"`
	Desc        string `json:"desc"`
}

type OutputPort struct {
	Name string `json:"name"`
	Desc string `json:"desc"`
}

type ParamMeta struct {
	Name    string `json:"name"`
	Default any    `json:"default"`
	Desc    string `json:"desc"`
}

type ValidationResult struct {
	Valid    bool     `json:"valid"`
	Errors   []string `json:"errors"`
	Warnings []string `json:"warnings"`
}
