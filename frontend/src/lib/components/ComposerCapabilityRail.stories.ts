import type { Meta, StoryObj } from '@storybook/sveltekit';
import ComposerCapabilityRail from './ComposerCapabilityRail.svelte';
import type { DraftAttachment } from '$lib/types';

const staged: DraftAttachment[] = [
	{
		id: 'a1',
		kind: 'image',
		name: 'rack-layout.png',
		sizeBytes: 248_910,
		mimeType: 'image/png'
	},
	{
		id: 'a2',
		kind: 'audio',
		name: 'voice-note.m4a',
		sizeBytes: 1_180_440,
		mimeType: 'audio/mp4'
	},
	{
		id: 'a3',
		kind: 'file',
		name: 'runbook.md',
		sizeBytes: 5_320,
		mimeType: 'text/markdown'
	}
];

const meta = {
	title: 'Chat/ComposerCapabilityRail',
	component: ComposerCapabilityRail,
	tags: ['autodocs'],
	args: {
		attachments: [],
		onVoiceClick: () => {},
		onImagePickClick: () => {},
		onAudioPickClick: () => {},
		onFilePickClick: () => {},
		onRemoveAttachment: () => {}
	}
} satisfies Meta<typeof ComposerCapabilityRail>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};

export const WithAttachments: Story = {
	args: {
		attachments: staged
	}
};
