import type { AgentName } from '$lib/types';

export interface FontDef {
	family: string;
	weights: number[];
	source:
		| { type: 'google'; family: string }
		| { type: 'local'; files: Record<number, string> }
		| { type: 'system' };
	fallback: string;
}

export interface ThemeConfig {
	id: string;
	name: string;

	colors: {
		canvas: string;
		surface: string;
		surfaceRaised: string;
		overlay: string;
		inset: string;
		border: string;
		borderMuted: string;
		borderEmphasis: string;
		textPrimary: string;
		textSecondary: string;
		textMuted: string;
		textLink: string;
		success: string;
		warning: string;
		error: string;
		info: string;
		focus: string;
		agents: Record<AgentName, string>;
	};

	fonts: {
		sans: FontDef;
		mono: FontDef;
		display?: FontDef;
	};

	atmosphere: {
		backgroundEffect?: string;
		surfaceTexture?: string;
		borderStyle?: string;
		glowColor?: string;
		noiseOpacity?: number;
	};

	animations: {
		easing: string;
		durationScale: number;
		portraitStyle: 'smooth' | 'stepped';
	};

	portraitFrame: {
		shape: 'circle' | 'square' | 'hexagon' | 'diamond' | 'none';
		border: string;
		background: string;
		glow?: string;
	};

	components: {
		statusBar: {
			background: string;
			separator: string;
			fontFamily: 'mono' | 'sans';
		};
		modeRail: {
			iconWeight: number;
			activeIndicator: 'bar' | 'glow' | 'fill' | 'underline';
		};
		chatPanel: {
			userMessageBg: string;
			assistantMessageBg: string;
			maxWidth: string;
			messagePadding: string;
		};
		toolCard: {
			statusBorderWidth: string;
			expandAnimation: 'slide' | 'fade' | 'instant';
		};
		confirmCard: {
			urgencyStyle: 'border' | 'glow' | 'pulse-bg';
			countdownStyle: 'bar' | 'ring' | 'text';
		};
		codeBlock: {
			shikiTheme: string;
			headerStyle: 'tab' | 'bar' | 'minimal' | 'none';
		};
		sidebar: {
			resizeHandle: 'native' | 'custom-bar' | 'hover-edge';
			activeSessionIndicator: 'left-border' | 'background' | 'glow';
		};
	};

	details: {
		borderRadius: string;
		scrollbarWidth: 'thin' | 'auto' | 'none';
		selectionBg: string;
		selectionText: string;
		textOnAccent: string;
		kbdStyle: 'beveled' | 'flat' | 'outline';
	};
}
