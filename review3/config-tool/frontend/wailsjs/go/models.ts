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
	    apiPort: number;
	    apiHost: string;
	    runtimeName: string;
	    enableOpcUa: boolean;

	    static createFrom(source: any = {}) {
	        return new StartParams(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.configPath = source["configPath"];
	        this.mode = source["mode"];
	        this.cycleTime = source["cycleTime"];
	        this.port = source["port"];
	        this.apiPort = source["apiPort"];
	        this.apiHost = source["apiHost"];
	        this.runtimeName = source["runtimeName"];
	        this.enableOpcUa = source["enableOpcUa"];
	    }
	}
	export class SystemStatus {
	    running: boolean;
	    apiReady: boolean;
	    pid: number;
	    configPath: string;
	    mode: string;
	    cycleTime: number;
	    port: number;
	    apiPort: number;
	    apiHost: string;
	    runtimeName: string;
	    startedAt: string;
	    configHash: string;
	    lastError: string;

	    static createFrom(source: any = {}) {
	        return new SystemStatus(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.running = source["running"];
	        this.apiReady = source["apiReady"];
	        this.pid = source["pid"];
	        this.configPath = source["configPath"];
	        this.mode = source["mode"];
	        this.cycleTime = source["cycleTime"];
	        this.port = source["port"];
	        this.apiPort = source["apiPort"];
	        this.apiHost = source["apiHost"];
	        this.runtimeName = source["runtimeName"];
	        this.startedAt = source["startedAt"];
	        this.configHash = source["configHash"];
	        this.lastError = source["lastError"];
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

	export class PIDPresence {
	    PB: boolean;
	    TI: boolean;
	    TD: boolean;
	    KD: boolean;
	    SV: boolean;
	    MV: boolean;
	    MODE: boolean;
	    SWPN: boolean;
	    SVSCL: boolean;
	    SVSCH: boolean;
	    SVL: boolean;
	    SVH: boolean;
	    MVSCL: boolean;
	    MVSCH: boolean;
	    MVL: boolean;
	    MVH: boolean;

	    static createFrom(source: any = {}) {
	        return new PIDPresence(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.PB = source["PB"];
	        this.TI = source["TI"];
	        this.TD = source["TD"];
	        this.KD = source["KD"];
	        this.SV = source["SV"];
	        this.MV = source["MV"];
	        this.MODE = source["MODE"];
	        this.SWPN = source["SWPN"];
	        this.SVSCL = source["SVSCL"];
	        this.SVSCH = source["SVSCH"];
	        this.SVL = source["SVL"];
	        this.SVH = source["SVH"];
	        this.MVSCL = source["MVSCL"];
	        this.MVSCH = source["MVSCH"];
	        this.MVL = source["MVL"];
	        this.MVH = source["MVH"];
	    }
	}
	export class TankPresence {
	    height: boolean;
	    radius: boolean;
	    outletArea: boolean;
	    initialLevel: boolean;

	    static createFrom(source: any = {}) {
	        return new TankPresence(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.height = source["height"];
	        this.radius = source["radius"];
	        this.outletArea = source["outletArea"];
	        this.initialLevel = source["initialLevel"];
	    }
	}
	export class ValvePresence {
	    fullTravelTime: boolean;
	    initialOpening: boolean;
	    flowCoefficient: boolean;
	    minOpening: boolean;
	    maxOpening: boolean;

	    static createFrom(source: any = {}) {
	        return new ValvePresence(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.fullTravelTime = source["fullTravelTime"];
	        this.initialOpening = source["initialOpening"];
	        this.flowCoefficient = source["flowCoefficient"];
	        this.minOpening = source["minOpening"];
	        this.maxOpening = source["maxOpening"];
	    }
	}
	export class FieldPresence {
	    cycleTime: boolean;
	    clockMode: boolean;
	    sourceFlow: boolean;
	    valve: ValvePresence;
	    tank1: TankPresence;
	    tank2: TankPresence;
	    pid: PIDPresence;

	    static createFrom(source: any = {}) {
	        return new FieldPresence(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.cycleTime = source["cycleTime"];
	        this.clockMode = source["clockMode"];
	        this.sourceFlow = source["sourceFlow"];
	        this.valve = this.convertValues(source["valve"], ValvePresence);
	        this.tank1 = this.convertValues(source["tank1"], TankPresence);
	        this.tank2 = this.convertValues(source["tank2"], TankPresence);
	        this.pid = this.convertValues(source["pid"], PIDPresence);
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


	export class PIDConfig {
	    PB: number;
	    TI: number;
	    TD: number;
	    KD: number;
	    SV: number;
	    MV: number;
	    MODE: number;
	    SWPN: number;
	    SVSCL: number;
	    SVSCH: number;
	    SVL: number;
	    SVH: number;
	    MVSCL: number;
	    MVSCH: number;
	    MVL: number;
	    MVH: number;

	    static createFrom(source: any = {}) {
	        return new PIDConfig(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.PB = source["PB"];
	        this.TI = source["TI"];
	        this.TD = source["TD"];
	        this.KD = source["KD"];
	        this.SV = source["SV"];
	        this.MV = source["MV"];
	        this.MODE = source["MODE"];
	        this.SWPN = source["SWPN"];
	        this.SVSCL = source["SVSCL"];
	        this.SVSCH = source["SVSCH"];
	        this.SVL = source["SVL"];
	        this.SVH = source["SVH"];
	        this.MVSCL = source["MVSCL"];
	        this.MVSCH = source["MVSCH"];
	        this.MVL = source["MVL"];
	        this.MVH = source["MVH"];
	    }
	}



	export class TemplatePatch {
	    path: string;
	    value: number;

	    static createFrom(source: any = {}) {
	        return new TemplatePatch(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.path = source["path"];
	        this.value = source["value"];
	    }
	}
	export class SaveTemplateRequest {
	    sourcePath: string;
	    targetPath: string;
	    expectedHash: string;
	    patches: TemplatePatch[];
	    allowOverwrite: boolean;

	    static createFrom(source: any = {}) {
	        return new SaveTemplateRequest(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.sourcePath = source["sourcePath"];
	        this.targetPath = source["targetPath"];
	        this.expectedHash = source["expectedHash"];
	        this.patches = this.convertValues(source["patches"], TemplatePatch);
	        this.allowOverwrite = source["allowOverwrite"];
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
	export class TemplateProgramTopology {
	    name: string;
	    type: string;
	    inputs: Record<string, string>;
	    executeFirst: boolean;

	    static createFrom(source: any = {}) {
	        return new TemplateProgramTopology(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.type = source["type"];
	        this.inputs = source["inputs"];
	        this.executeFirst = source["executeFirst"];
	    }
	}
	export class TemplateTopology {
	    programs: TemplateProgramTopology[];

	    static createFrom(source: any = {}) {
	        return new TemplateTopology(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.programs = this.convertValues(source["programs"], TemplateProgramTopology);
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
	export class TankConfig {
	    height: number;
	    radius: number;
	    outletArea: number;
	    initialLevel: number;

	    static createFrom(source: any = {}) {
	        return new TankConfig(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.height = source["height"];
	        this.radius = source["radius"];
	        this.outletArea = source["outletArea"];
	        this.initialLevel = source["initialLevel"];
	    }
	}
	export class ValveConfig {
	    fullTravelTime: number;
	    initialOpening: number;
	    flowCoefficient: number;
	    minOpening: number;
	    maxOpening: number;

	    static createFrom(source: any = {}) {
	        return new ValveConfig(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.fullTravelTime = source["fullTravelTime"];
	        this.initialOpening = source["initialOpening"];
	        this.flowCoefficient = source["flowCoefficient"];
	        this.minOpening = source["minOpening"];
	        this.maxOpening = source["maxOpening"];
	    }
	}
	export class TemplateConfig {
	    cycleTime: number;
	    clockMode: string;
	    sourceFlow: number;
	    valve: ValveConfig;
	    tank1: TankConfig;
	    tank2: TankConfig;
	    pid: PIDConfig;

	    static createFrom(source: any = {}) {
	        return new TemplateConfig(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.cycleTime = source["cycleTime"];
	        this.clockMode = source["clockMode"];
	        this.sourceFlow = source["sourceFlow"];
	        this.valve = this.convertValues(source["valve"], ValveConfig);
	        this.tank1 = this.convertValues(source["tank1"], TankConfig);
	        this.tank2 = this.convertValues(source["tank2"], TankConfig);
	        this.pid = this.convertValues(source["pid"], PIDConfig);
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
	export class TemplateDocument {
	    path: string;
	    contentHash: string;
	    config: TemplateConfig;
	    presence: FieldPresence;
	    topology: TemplateTopology;
	    warnings: string[];

	    static createFrom(source: any = {}) {
	        return new TemplateDocument(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.path = source["path"];
	        this.contentHash = source["contentHash"];
	        this.config = this.convertValues(source["config"], TemplateConfig);
	        this.presence = this.convertValues(source["presence"], FieldPresence);
	        this.topology = this.convertValues(source["topology"], TemplateTopology);
	        this.warnings = source["warnings"];
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
	export class SaveTemplateResult {
	    newPath: string;
	    newHash: string;
	    newDocument: TemplateDocument;

	    static createFrom(source: any = {}) {
	        return new SaveTemplateResult(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.newPath = source["newPath"];
	        this.newHash = source["newHash"];
	        this.newDocument = this.convertValues(source["newDocument"], TemplateDocument);
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







	export class ValidationIssue {
	    path: string;
	    level: string;
	    message: string;

	    static createFrom(source: any = {}) {
	        return new ValidationIssue(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.path = source["path"];
	        this.level = source["level"];
	        this.message = source["message"];
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

export namespace yaml {

	export class Node {
	    Kind: number;
	    Style: number;
	    Tag: string;
	    Value: string;
	    Anchor: string;
	    Alias?: Node;
	    Content: Node[];
	    HeadComment: string;
	    LineComment: string;
	    FootComment: string;
	    Line: number;
	    Column: number;

	    static createFrom(source: any = {}) {
	        return new Node(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.Kind = source["Kind"];
	        this.Style = source["Style"];
	        this.Tag = source["Tag"];
	        this.Value = source["Value"];
	        this.Anchor = source["Anchor"];
	        this.Alias = this.convertValues(source["Alias"], Node);
	        this.Content = this.convertValues(source["Content"], Node);
	        this.HeadComment = source["HeadComment"];
	        this.LineComment = source["LineComment"];
	        this.FootComment = source["FootComment"];
	        this.Line = source["Line"];
	        this.Column = source["Column"];
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

}

