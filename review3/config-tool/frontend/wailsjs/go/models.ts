export namespace bindings {
	
	export class BatchResult {
	    columns: string[];
	    rows: any[];
	
	    static createFrom(source: any = {}) {
	        return new BatchResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.columns = source["columns"];
	        this.rows = source["rows"];
	    }
	}
	export class StartParams {
	    configPath: string;
	    mode: string;
	    cycleTime: number;
	    port: number;
	
	    static createFrom(source: any = {}) {
	        return new StartParams(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.configPath = source["configPath"];
	        this.mode = source["mode"];
	        this.cycleTime = source["cycleTime"];
	        this.port = source["port"];
	    }
	}
	export class SystemStatus {
	    running: boolean;
	    pid: number;
	    configPath: string;
	    mode: string;
	    cycleTime: number;
	    port: number;
	
	    static createFrom(source: any = {}) {
	        return new SystemStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.running = source["running"];
	        this.pid = source["pid"];
	        this.configPath = source["configPath"];
	        this.mode = source["mode"];
	        this.cycleTime = source["cycleTime"];
	        this.port = source["port"];
	    }
	}

}

export namespace config {
	
	export class Position {
	    x: number;
	    y: number;
	
	    static createFrom(source: any = {}) {
	        return new Position(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.x = source["x"];
	        this.y = source["y"];
	    }
	}
	export class BlockNode {
	    id: string;
	    name: string;
	    type: string;
	    position: Position;
	    params: Record<string, any>;
	    executeFirst: boolean;
	
	    static createFrom(source: any = {}) {
	        return new BlockNode(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.type = source["type"];
	        this.position = this.convertValues(source["position"], Position);
	        this.params = source["params"];
	        this.executeFirst = source["executeFirst"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	export class Connection {
	    id: string;
	    source: string;
	    sourcePort: string;
	    target: string;
	    targetPort: string;
	
	    static createFrom(source: any = {}) {
	        return new Connection(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.source = source["source"];
	        this.sourcePort = source["sourcePort"];
	        this.target = source["target"];
	        this.targetPort = source["targetPort"];
	    }
	}
	export class ClockConfig {
	    mode: string;
	    cycleTime: number;
	
	    static createFrom(source: any = {}) {
	        return new ClockConfig(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mode = source["mode"];
	        this.cycleTime = source["cycleTime"];
	    }
	}
	export class CanvasState {
	    clock: ClockConfig;
	    nodes: BlockNode[];
	    edges: Connection[];
	
	    static createFrom(source: any = {}) {
	        return new CanvasState(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.clock = this.convertValues(source["clock"], ClockConfig);
	        this.nodes = this.convertValues(source["nodes"], BlockNode);
	        this.edges = this.convertValues(source["edges"], Connection);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class ParamMeta {
	    name: string;
	    default: any;
	    desc: string;
	
	    static createFrom(source: any = {}) {
	        return new ParamMeta(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.default = source["default"];
	        this.desc = source["desc"];
	    }
	}
	export class OutputPort {
	    name: string;
	    desc: string;
	
	    static createFrom(source: any = {}) {
	        return new OutputPort(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.desc = source["desc"];
	    }
	}
	export class InputPort {
	    name: string;
	    type: string;
	    connectable: boolean;
	    desc: string;
	
	    static createFrom(source: any = {}) {
	        return new InputPort(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.type = source["type"];
	        this.connectable = source["connectable"];
	        this.desc = source["desc"];
	    }
	}
	export class ComponentMeta {
	    type: string;
	    category: string;
	    displayName: string;
	    inputs: InputPort[];
	    outputs: OutputPort[];
	    params: ParamMeta[];
	    doc: string;
	
	    static createFrom(source: any = {}) {
	        return new ComponentMeta(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.type = source["type"];
	        this.category = source["category"];
	        this.displayName = source["displayName"];
	        this.inputs = this.convertValues(source["inputs"], InputPort);
	        this.outputs = this.convertValues(source["outputs"], OutputPort);
	        this.params = this.convertValues(source["params"], ParamMeta);
	        this.doc = source["doc"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	
	
	
	
	export class ValidationResult {
	    valid: boolean;
	    errors: string[];
	    warnings: string[];
	
	    static createFrom(source: any = {}) {
	        return new ValidationResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.valid = source["valid"];
	        this.errors = source["errors"];
	        this.warnings = source["warnings"];
	    }
	}

}

