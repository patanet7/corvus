import type { PortraitConfig, SvgPathDef } from './types';

function svgAsset(
	viewBox: string,
	bgPath: string,
	fgPath: string,
	overlayStrokePath?: string
): PortraitConfig['states']['idle'] {
	const paths: SvgPathDef[] = [
		{ d: bgPath, fill: 'currentColor', opacity: 0.2 },
		{ d: bgPath, fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
		{ d: fgPath, fill: 'currentColor', opacity: 0.8 }
	];
	if (overlayStrokePath) {
		paths.push({
			d: overlayStrokePath,
			fill: 'none',
			stroke: 'currentColor',
			strokeWidth: 2,
			opacity: 0.75
		});
	}
	return { type: 'svg', viewBox, paths };
}

/**
 * Build an SVG PortraitConfig from background + foreground path data.
 * Uses 'currentColor' so the SvgRenderer can set the agent color via CSS.
 * Reproduces the Phase 1 rendering: bg filled at 0.2, bg stroked, fg filled at 0.8.
 */
function svgPortrait(
	agent: string,
	viewBox: string,
	bgPath: string,
	fgPath: string
): PortraitConfig {
	const idle = svgAsset(viewBox, bgPath, fgPath);
	const thinking = svgAsset(viewBox, bgPath, fgPath, 'M24 8 A16 16 0 1 1 23.99 8');
	const streaming = svgAsset(viewBox, bgPath, fgPath, 'M12 24 H36 M24 12 V36');
	const done = svgAsset(viewBox, bgPath, fgPath, 'M16 24 L22 30 L33 18');
	const error = svgAsset(viewBox, bgPath, fgPath, 'M17 17 L31 31 M31 17 L17 31');
	return {
		agent,
		states: {
			idle,
			thinking,
			streaming,
			done,
			error
		}
	};
}

/** Default geometric SVG portraits for all built-in agents. */
export const DEFAULT_PORTRAITS: Record<string, PortraitConfig> = {
	personal: svgPortrait(
		'personal',
		'0 0 48 48',
		// Circle
		'M24 4 A20 20 0 1 1 24 44 A20 20 0 1 1 24 4 Z',
		// Person silhouette
		'M24 16 C20 16 18 20 18 24 C18 28 20 30 24 32 C28 30 30 28 30 24 C30 20 28 16 24 16 Z M24 12 A4 4 0 1 1 24 20 A4 4 0 1 1 24 12 Z'
	),
	work: svgPortrait(
		'work',
		'0 0 48 48',
		// Rounded rect
		'M8 8 H40 Q44 8 44 12 V36 Q44 40 40 40 H8 Q4 40 4 36 V12 Q4 8 8 8 Z',
		// Briefcase
		'M16 20 H32 V32 H16 Z M20 16 H28 V20 H20 Z'
	),
	homelab: svgPortrait(
		'homelab',
		'0 0 48 48',
		// Hexagon
		'M24 4 L44 16 V32 L24 44 L4 32 V16 Z',
		// Terminal cursor
		'M16 28 H22 V24 H16 Z M26 28 L26 28'
	),
	finance: svgPortrait(
		'finance',
		'0 0 48 48',
		// Shield
		'M24 4 L40 14 V34 L24 44 L8 34 V14 Z',
		// S shape
		'M24 14 C20 14 18 16 18 18 C18 22 24 22 24 24 C24 26 18 26 18 30 C18 32 20 34 24 34 C28 34 30 32 30 30 C30 26 24 26 24 24 C24 22 30 22 30 18 C30 16 28 14 24 14 Z'
	),
	email: svgPortrait(
		'email',
		'0 0 48 48',
		// Rectangle envelope
		'M6 12 L42 12 L42 36 L6 36 Z',
		// Envelope flap
		'M6 12 L24 24 L42 12'
	),
	docs: svgPortrait(
		'docs',
		'0 0 48 48',
		// Document with folded corner
		'M10 6 H34 L38 10 V42 H10 Z',
		// Magnifying glass
		'M18 20 A6 6 0 1 1 18 32 A6 6 0 1 1 18 20 Z M24 26 L30 32'
	),
	music: svgPortrait(
		'music',
		'0 0 48 48',
		// Circle
		'M24 4 A20 20 0 1 1 24 44 A20 20 0 1 1 24 4 Z',
		// Eighth note
		'M28 14 V30 A4 4 0 1 1 24 30 V18 L28 14'
	),
	home: svgPortrait(
		'home',
		'0 0 48 48',
		// House pentagon
		'M24 6 L42 22 V40 H6 V22 Z',
		// Window dot
		'M20 28 A4 4 0 1 1 28 28 A4 4 0 1 1 20 28'
	),
	huginn: svgPortrait(
		'huginn',
		'0 0 48 48',
		// Diamond
		'M24 4 L42 24 L24 44 L6 24 Z',
		// Raven eye + beak motif
		'M16 26 C20 18 28 16 34 20 L28 24 C24 22 21 23 18 27 Z M28 24 L36 26 L30 30 Z M20 20 A2 2 0 1 1 24 20 A2 2 0 1 1 20 20'
	),
	general: svgPortrait(
		'general',
		'0 0 48 48',
		// Circle
		'M24 4 A20 20 0 1 1 24 44 A20 20 0 1 1 24 4 Z',
		// Bird silhouette (corvus)
		'M14 30 C14 22 18 16 24 14 C28 14 32 16 34 20 L30 22 C28 20 26 18 24 18 C22 18 20 20 18 24 L16 28 Z M30 28 L34 24 L38 30 C36 34 30 36 24 36 C20 36 16 34 14 30 Z'
	)
};
