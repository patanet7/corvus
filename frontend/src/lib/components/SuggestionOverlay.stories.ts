import type { Meta, StoryObj } from '@storybook/sveltekit';
import SuggestionOverlay from './SuggestionOverlay.svelte';

const meta = {
	title: 'Chat/SuggestionOverlay',
	component: SuggestionOverlay,
	tags: ['autodocs'],
	args: {
		items: [
			{ id: 'a-general', label: '@general', description: 'Route to general router agent' },
			{ id: 'a-homelab', label: '@homelab', description: 'Route directly to homelab agent' },
			{ id: 'cmd-model', label: '/model', description: 'Set explicit model override' }
		],
		activeIndex: 0,
		onSelect: () => {}
	}
} satisfies Meta<typeof SuggestionOverlay>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const SecondActive: Story = {
	args: {
		activeIndex: 1
	}
};
