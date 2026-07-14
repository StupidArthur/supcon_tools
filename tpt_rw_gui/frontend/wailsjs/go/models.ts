export namespace bindings {
	
	export class AppInfoDTO {
	    name: string;
	    version: string;
	    title: string;
	
	    static createFrom(source: any = {}) {
	        return new AppInfoDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.version = source["version"];
	        this.title = source["title"];
	    }
	}
	export class DataSourceDTO {
	    id: number;
	    name: string;
	    url: string;
	    dsType: number;
	    dsSubType: number;
	    alive: boolean;
	    dsStatus: number;
	
	    static createFrom(source: any = {}) {
	        return new DataSourceDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.name = source["name"];
	        this.url = source["url"];
	        this.dsType = source["dsType"];
	        this.dsSubType = source["dsSubType"];
	        this.alive = source["alive"];
	        this.dsStatus = source["dsStatus"];
	    }
	}
	export class HistoryRowDTO {
	    tagName: string;
	    value: string;
	    appTime: string;
	    quality: number;
	
	    static createFrom(source: any = {}) {
	        return new HistoryRowDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.tagName = source["tagName"];
	        this.value = source["value"];
	        this.appTime = source["appTime"];
	        this.quality = source["quality"];
	    }
	}
	export class ListTagsRequestDTO {
	    dsId?: number;
	    keyword: string;
	    page: number;
	    pageSize: number;
	
	    static createFrom(source: any = {}) {
	        return new ListTagsRequestDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.dsId = source["dsId"];
	        this.keyword = source["keyword"];
	        this.page = source["page"];
	        this.pageSize = source["pageSize"];
	    }
	}
	export class LoginRequestDTO {
	    url: string;
	    username: string;
	    password: string;
	    tenantId: string;
	    timeoutSec: number;
	
	    static createFrom(source: any = {}) {
	        return new LoginRequestDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.url = source["url"];
	        this.username = source["username"];
	        this.password = source["password"];
	        this.tenantId = source["tenantId"];
	        this.timeoutSec = source["timeoutSec"];
	    }
	}
	export class RTValueDTO {
	    tagName: string;
	    value: string;
	    tagTime: string;
	    appTime: string;
	    quality: number;
	    dataType: number;
	    dsId: number;
	    isSuccess: boolean;
	    message?: string;
	
	    static createFrom(source: any = {}) {
	        return new RTValueDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.tagName = source["tagName"];
	        this.value = source["value"];
	        this.tagTime = source["tagTime"];
	        this.appTime = source["appTime"];
	        this.quality = source["quality"];
	        this.dataType = source["dataType"];
	        this.dsId = source["dsId"];
	        this.isSuccess = source["isSuccess"];
	        this.message = source["message"];
	    }
	}
	export class ReadHistoryRequestDTO {
	    tagNames: string[];
	    begTime: string;
	    endTime: string;
	    interval: number;
	    isSecond: boolean;
	    isSource: boolean;
	    offset: number;
	    option: number;
	    page: number;
	    pageSize: number;
	    sort: string;
	    mode: string;
	    numberToString: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ReadHistoryRequestDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.tagNames = source["tagNames"];
	        this.begTime = source["begTime"];
	        this.endTime = source["endTime"];
	        this.interval = source["interval"];
	        this.isSecond = source["isSecond"];
	        this.isSource = source["isSource"];
	        this.offset = source["offset"];
	        this.option = source["option"];
	        this.page = source["page"];
	        this.pageSize = source["pageSize"];
	        this.sort = source["sort"];
	        this.mode = source["mode"];
	        this.numberToString = source["numberToString"];
	    }
	}
	export class SessionInfoDTO {
	    loggedIn: boolean;
	    url: string;
	    tenantId: string;
	
	    static createFrom(source: any = {}) {
	        return new SessionInfoDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.loggedIn = source["loggedIn"];
	        this.url = source["url"];
	        this.tenantId = source["tenantId"];
	    }
	}
	export class TagDTO {
	    id: number;
	    tagName: string;
	    tagBaseName: string;
	    tagType: number;
	    dsId: number;
	    dsName: string;
	    dataType: number;
	    dataTypeName: string;
	    tagValue?: string;
	    tagTime: string;
	    quality: number;
	    groupName: string;
	
	    static createFrom(source: any = {}) {
	        return new TagDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.tagName = source["tagName"];
	        this.tagBaseName = source["tagBaseName"];
	        this.tagType = source["tagType"];
	        this.dsId = source["dsId"];
	        this.dsName = source["dsName"];
	        this.dataType = source["dataType"];
	        this.dataTypeName = source["dataTypeName"];
	        this.tagValue = source["tagValue"];
	        this.tagTime = source["tagTime"];
	        this.quality = source["quality"];
	        this.groupName = source["groupName"];
	    }
	}
	export class WriteRequestDTO {
	    values: Record<string, any>;
	    readbackDelayMs: number;
	
	    static createFrom(source: any = {}) {
	        return new WriteRequestDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.values = source["values"];
	        this.readbackDelayMs = source["readbackDelayMs"];
	    }
	}
	export class WriteResultDTO {
	    written: string[];
	    fails?: Record<string, string>;
	    readback?: RTValueDTO[];
	
	    static createFrom(source: any = {}) {
	        return new WriteResultDTO(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.written = source["written"];
	        this.fails = source["fails"];
	        this.readback = this.convertValues(source["readback"], RTValueDTO);
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

