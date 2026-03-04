import { describe, expect, it } from 'vitest';

import type { AgentName } from '$lib/types';
import { parseAgentMention, parseSlashCommand } from './composer';

const knownAgents = new Set<AgentName>(['work', 'homelab', 'general', 'huginn', 'home']);

function isKnownAgent(name: string): name is AgentName {
	return knownAgents.has(name as AgentName);
}

describe('parseAgentMention', () => {
	it('parses known @agent prefix and strips it from outbound message', () => {
		expect(parseAgentMention('@homelab restart plex', isKnownAgent)).toEqual({
			message: 'restart plex',
			targetAgent: 'homelab'
		});
	});

	it('returns original message when only @ is present', () => {
		expect(parseAgentMention('@', isKnownAgent)).toEqual({
			message: '@'
		});
	});

	it('returns original message for unknown agents', () => {
		expect(parseAgentMention('@unknown hello', isKnownAgent)).toEqual({
			message: '@unknown hello'
		});
	});

	it('supports escaped @@ prefix', () => {
		expect(parseAgentMention('@@work hello', isKnownAgent)).toEqual({
			message: '@work hello'
		});
	});

	it('supports multiline message body', () => {
		expect(parseAgentMention('@work first line\nsecond line', isKnownAgent)).toEqual({
			message: 'first line\nsecond line',
			targetAgent: 'work'
		});
	});

	it('supports @all fan-out mention', () => {
		expect(parseAgentMention('@all summarize updates', isKnownAgent)).toEqual({
			message: 'summarize updates',
			targetAgents: ['@all']
		});
	});
});

describe('parseSlashCommand', () => {
	it('parses command with arguments', () => {
		expect(parseSlashCommand('/model claude-sonnet-4-6')).toEqual({
			command: 'model',
			args: ['claude-sonnet-4-6'],
			rawArgs: 'claude-sonnet-4-6'
		});
	});

	it('parses command without arguments', () => {
		expect(parseSlashCommand('/new')).toEqual({
			command: 'new',
			args: [],
			rawArgs: ''
		});
	});

	it('returns null when input is not slash command', () => {
		expect(parseSlashCommand('hello')).toBeNull();
	});
});
