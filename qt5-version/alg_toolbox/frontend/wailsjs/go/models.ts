export namespace main {
	
	export class CSVRecord {
	    name: string;
	    release: string;
	    cores: string;
	    replicas: string;
	    position: string;
	
	    static createFrom(source: any = {}) {
	        return new CSVRecord(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.release = source["release"];
	        this.cores = source["cores"];
	        this.replicas = source["replicas"];
	        this.position = source["position"];
	    }
	}
	export class PublishItem {
	    id: number;
	    name: string;
	    cores: number;
	    numReplicas: number;
	    resourceType: number;
	
	    static createFrom(source: any = {}) {
	        return new PublishItem(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.cores = source["cores"];
	        this.numReplicas = source["numReplicas"];
	        this.resourceType = source["resourceType"];
	    }
	}
	export class CompareResult {
	    differences: string[];
	    toRelease: PublishItem[];
	    alreadyReleased: string[];
	    shouldNotRelease: string[];
	    notInPlatform: string[];
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new CompareResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.differences = source["differences"];
	        this.toRelease = this.convertValues(source["toRelease"], PublishItem);
	        this.alreadyReleased = source["alreadyReleased"];
	        this.shouldNotRelease = source["shouldNotRelease"];
	        this.notInPlatform = source["notInPlatform"];
	        this.error = source["error"];
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
	export class ConnectResult {
	    success: boolean;
	    count: number;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new ConnectResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.success = source["success"];
	        this.count = source["count"];
	        this.error = source["error"];
	    }
	}
	export class LoadCSVResult {
	    records: CSVRecord[];
	    count: number;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new LoadCSVResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.records = this.convertValues(source["records"], CSVRecord);
	        this.count = source["count"];
	        this.error = source["error"];
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
	
	export class PublishStartResult {
	    started: boolean;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new PublishStartResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.started = source["started"];
	        this.error = source["error"];
	    }
	}
	export class PublishedAlgosResult {
	    algos: any[];
	    count: number;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new PublishedAlgosResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.algos = source["algos"];
	        this.count = source["count"];
	        this.error = source["error"];
	    }
	}
	export class SyncStartResult {
	    started: boolean;
	    error: string;
	
	    static createFrom(source: any = {}) {
	        return new SyncStartResult(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.started = source["started"];
	        this.error = source["error"];
	    }
	}

}

