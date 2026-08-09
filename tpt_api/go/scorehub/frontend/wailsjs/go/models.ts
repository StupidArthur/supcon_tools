export namespace batch {
	
	export class EvalConfig {
	    id: number;
	    pracLoadEnabled: number;
	    examLoadEnabled: number;
	    evalDurationMinutes: number;
	    addTime: string;
	    updateTime: string;
	
	    static createFrom(source: any = {}) {
	        return new EvalConfig(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.pracLoadEnabled = source["pracLoadEnabled"];
	        this.examLoadEnabled = source["examLoadEnabled"];
	        this.evalDurationMinutes = source["evalDurationMinutes"];
	        this.addTime = source["addTime"];
	        this.updateTime = source["updateTime"];
	    }
	}
	export class UpdateResult {
	    success: boolean;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new UpdateResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.error = source["error"];
	    }
	}

}

export namespace monitor {
	
	export class Report {
	    name: string;
	    tenantId: string;
	    dsName: string;
	    dsTarUrl: string;
	    dsFound: boolean;
	    dsAlive: boolean;
	    tagTotal: number;
	    tagGood: number;
	    badTags: string[];
	    error: string;
	    sampleValue: string;
	    sampleTime: string;
	
	    static createFrom(source: any = {}) {
	        return new Report(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.tenantId = source["tenantId"];
	        this.dsName = source["dsName"];
	        this.dsTarUrl = source["dsTarUrl"];
	        this.dsFound = source["dsFound"];
	        this.dsAlive = source["dsAlive"];
	        this.tagTotal = source["tagTotal"];
	        this.tagGood = source["tagGood"];
	        this.badTags = source["badTags"];
	        this.error = source["error"];
	        this.sampleValue = source["sampleValue"];
	        this.sampleTime = source["sampleTime"];
	    }
	}
	export class AbnormalEntry {
	    at: string;
	    report: Report;
	
	    static createFrom(source: any = {}) {
	        return new AbnormalEntry(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.at = source["at"];
	        this.report = this.convertValues(source["report"], Report);
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
	export class Cycle {
	    at: string;
	    durMs: number;
	    skipped: boolean;
	    reports: Report[];
	
	    static createFrom(source: any = {}) {
	        return new Cycle(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.at = source["at"];
	        this.durMs = source["durMs"];
	        this.skipped = source["skipped"];
	        this.reports = this.convertValues(source["reports"], Report);
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
	
	export class Snapshot {
	    cycle: Cycle;
	    abnormal: AbnormalEntry[];
	
	    static createFrom(source: any = {}) {
	        return new Snapshot(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.cycle = this.convertValues(source["cycle"], Cycle);
	        this.abnormal = this.convertValues(source["abnormal"], AbnormalEntry);
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

export namespace personal {
	
	export class CleanupResult {
	    success: boolean;
	    counts: Record<string, number>;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new CleanupResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.counts = source["counts"];
	        this.error = source["error"];
	    }
	}
	export class FileRecord {
	    id: string;
	    fileName: string;
	    uploadTime: string;
	    score?: number;
	
	    static createFrom(source: any = {}) {
	        return new FileRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.fileName = source["fileName"];
	        this.uploadTime = source["uploadTime"];
	        this.score = source["score"];
	    }
	}
	export class ScoreRecord {
	    id: string;
	    score?: number;
	    sci?: number;
	    se?: number;
	    ssafe?: number;
	    ssmi?: number;
	    status: number;
	    algorithmType: string;
	    startWorktime: string;
	    endWorktime: string;
	    isBest: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ScoreRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.score = source["score"];
	        this.sci = source["sci"];
	        this.se = source["se"];
	        this.ssafe = source["ssafe"];
	        this.ssmi = source["ssmi"];
	        this.status = source["status"];
	        this.algorithmType = source["algorithmType"];
	        this.startWorktime = source["startWorktime"];
	        this.endWorktime = source["endWorktime"];
	        this.isBest = source["isBest"];
	    }
	}
	export class Detail {
	    tenantId: string;
	    scoreRecords: ScoreRecord[];
	    files: FileRecord[];
	
	    static createFrom(source: any = {}) {
	        return new Detail(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.tenantId = source["tenantId"];
	        this.scoreRecords = this.convertValues(source["scoreRecords"], ScoreRecord);
	        this.files = this.convertValues(source["files"], FileRecord);
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
	
	export class Row {
	    seq: number;
	    name: string;
	    tenantId: string;
	    username: string;
	    totalScore?: number;
	
	    static createFrom(source: any = {}) {
	        return new Row(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.seq = source["seq"];
	        this.name = source["name"];
	        this.tenantId = source["tenantId"];
	        this.username = source["username"];
	        this.totalScore = source["totalScore"];
	    }
	}

}

export namespace ranking {
	
	export class Item {
	    rank: number;
	    tenantId: string;
	    name: string;
	    controlScore?: number;
	    softSensorScore?: number;
	    totalScore: number;
	
	    static createFrom(source: any = {}) {
	        return new Item(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.rank = source["rank"];
	        this.tenantId = source["tenantId"];
	        this.name = source["name"];
	        this.controlScore = source["controlScore"];
	        this.softSensorScore = source["softSensorScore"];
	        this.totalScore = source["totalScore"];
	    }
	}

}

export namespace team {
	
	export class Machine {
	    zkjs: string;
	    cloudId: string;
	
	    static createFrom(source: any = {}) {
	        return new Machine(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.zkjs = source["zkjs"];
	        this.cloudId = source["cloudId"];
	    }
	}
	export class Team {
	    seq: number;
	    name: string;
	    tenantId: string;
	    username: string;
	    machine: Machine;
	    ip: string;
	    type: string;
	
	    static createFrom(source: any = {}) {
	        return new Team(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.seq = source["seq"];
	        this.name = source["name"];
	        this.tenantId = source["tenantId"];
	        this.username = source["username"];
	        this.machine = this.convertValues(source["machine"], Machine);
	        this.ip = source["ip"];
	        this.type = source["type"];
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

