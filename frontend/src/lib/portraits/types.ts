/** A single SVG path element with optional styling attributes */
export interface SvgPathDef {
	d: string;
	fill?: string;
	stroke?: string;
	strokeWidth?: number;
	opacity?: number;
}

/** Discriminated union for portrait asset formats */
export type AssetDef =
	| {
			type: 'sprite';
			src: string;
			frameWidth: number;
			frameHeight: number;
			frameCount: number;
			fps: number;
	  }
	| { type: 'svg'; viewBox: string; paths: SvgPathDef[] }
	| { type: 'image'; src: string }
	| { type: 'animated'; src: string }
	| { type: 'lottie'; data: object };

/** Portrait configuration for a single agent */
export interface PortraitConfig {
	agent: string;
	states: {
		idle: AssetDef;
		thinking?: AssetDef;
		streaming?: AssetDef;
		done?: AssetDef;
		error?: AssetDef;
	};
	accentColor?: string;
}
