import { describe, it, expect, beforeEach } from 'vitest';
import type { PortraitConfig } from './types';
import { DEFAULT_PORTRAITS } from './defaults';
import { getPortrait, registerPortrait, listPortraits, resetPortraits } from './registry';

beforeEach(() => {
	resetPortraits();
});

describe('DEFAULT_PORTRAITS', () => {
	it('has a portrait for every agent', () => {
		for (const agent of Object.keys(DEFAULT_PORTRAITS)) {
			expect(DEFAULT_PORTRAITS[agent]).toBeDefined();
			expect(DEFAULT_PORTRAITS[agent].agent).toBe(agent);
		}
	});

	it('covers all 10 agents', () => {
		expect(Object.keys(DEFAULT_PORTRAITS)).toHaveLength(10);
	});

	it('all defaults use svg asset type', () => {
		for (const agent of Object.keys(DEFAULT_PORTRAITS)) {
			const portrait = DEFAULT_PORTRAITS[agent];
			expect(portrait.states.idle.type).toBe('svg');
		}
	});

	it('all SVG assets have viewBox and paths', () => {
		for (const agent of Object.keys(DEFAULT_PORTRAITS)) {
			const idle = DEFAULT_PORTRAITS[agent].states.idle;
			if (idle.type === 'svg') {
				expect(idle.viewBox).toBe('0 0 48 48');
				expect(idle.paths.length).toBeGreaterThan(0);
				for (const path of idle.paths) {
					expect(path.d).toBeTruthy();
				}
			}
		}
	});

	it('each default has 3 paths (bg fill, bg stroke, fg fill)', () => {
		for (const agent of Object.keys(DEFAULT_PORTRAITS)) {
			const idle = DEFAULT_PORTRAITS[agent].states.idle;
			if (idle.type === 'svg') {
				expect(idle.paths).toHaveLength(3);
				// bg filled
				expect(idle.paths[0].fill).toBe('currentColor');
				expect(idle.paths[0].opacity).toBe(0.2);
				// bg stroked
				expect(idle.paths[1].fill).toBe('none');
				expect(idle.paths[1].stroke).toBe('currentColor');
				expect(idle.paths[1].strokeWidth).toBe(2);
				// fg filled
				expect(idle.paths[2].fill).toBe('currentColor');
				expect(idle.paths[2].opacity).toBe(0.8);
			}
		}
	});

	it('all defaults include explicit state assets for lifecycle', () => {
		for (const agent of Object.keys(DEFAULT_PORTRAITS)) {
			const portrait = DEFAULT_PORTRAITS[agent];
			expect(portrait.states.thinking).toBeDefined();
			expect(portrait.states.streaming).toBeDefined();
			expect(portrait.states.done).toBeDefined();
			expect(portrait.states.error).toBeDefined();
			expect(portrait.states.thinking?.type).toBe('svg');
			expect(portrait.states.streaming?.type).toBe('svg');
			expect(portrait.states.done?.type).toBe('svg');
			expect(portrait.states.error?.type).toBe('svg');
		}
	});
});

describe('portrait registry', () => {
	it('returns default portrait when no custom is registered', () => {
		const portrait = getPortrait('general');
		expect(portrait).toBe(DEFAULT_PORTRAITS.general);
	});

	it('custom portrait overrides default', () => {
		const custom: PortraitConfig = {
			agent: 'homelab',
			states: {
				idle: { type: 'image', src: '/portraits/homelab/idle.png' }
			}
		};
		registerPortrait(custom);
		expect(getPortrait('homelab')).toBe(custom);
		expect(getPortrait('homelab').states.idle.type).toBe('image');
	});

	it('custom portrait does not affect other agents', () => {
		const custom: PortraitConfig = {
			agent: 'finance',
			states: {
				idle: { type: 'image', src: '/portraits/finance/idle.png' }
			}
		};
		registerPortrait(custom);
		expect(getPortrait('finance')).toBe(custom);
		expect(getPortrait('work')).toBe(DEFAULT_PORTRAITS.work);
	});

	it('listPortraits returns all 10 agents', () => {
		const portraits = listPortraits();
		expect(portraits).toHaveLength(10);
	});

	it('listPortraits includes custom overrides', () => {
		const custom: PortraitConfig = {
			agent: 'music',
			states: {
				idle: { type: 'animated', src: '/portraits/music/idle.gif' }
			}
		};
		registerPortrait(custom);
		const portraits = listPortraits();
		const musicPortrait = portraits.find((p) => p.agent === 'music');
		expect(musicPortrait).toBe(custom);
	});

	it('resetPortraits clears all custom overrides', () => {
		const custom: PortraitConfig = {
			agent: 'docs',
			states: {
				idle: { type: 'image', src: '/portraits/docs/idle.png' }
			}
		};
		registerPortrait(custom);
		expect(getPortrait('docs')).toBe(custom);
		resetPortraits();
		expect(getPortrait('docs')).toBe(DEFAULT_PORTRAITS.docs);
	});
});
