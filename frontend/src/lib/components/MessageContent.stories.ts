import type { Meta, StoryObj } from '@storybook/sveltekit';
import MessageContent from './MessageContent.svelte';

const markdown = [
	'### Deployment Summary',
	'',
	'- Updated model routing policy',
	'- Applied `@homelab` direct dispatch',
	'',
	'```bash',
	'docker ps --format "{{.Names}} {{.Status}}"',
	'```'
].join('\n');

const meta = {
	title: 'Chat/MessageContent',
	component: MessageContent,
	tags: ['autodocs'],
	args: {
		content: markdown,
		streaming: false,
		shikiTheme: 'github-dark'
	}
} satisfies Meta<typeof MessageContent>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Markdown: Story = {};

export const Streaming: Story = {
	args: {
		streaming: true,
		content: 'Generating answer...\n\n```ts\nconst status = "streaming";'
	}
};
