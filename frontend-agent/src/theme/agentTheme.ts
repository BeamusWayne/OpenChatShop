import type { ThemeConfig } from 'antd';

export const agentTheme: ThemeConfig = {
  token: {
    colorPrimary: '#ff5600',
    colorSuccess: '#0bdf50',
    colorError: '#c41c1c',
    colorWarning: '#d4a017',
    colorInfo: '#65b5ff',

    // Surface
    colorBgLayout: '#f5f1ec',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',

    // Text
    colorText: '#111111',
    colorTextSecondary: '#626260',
    colorTextTertiary: '#7b7b78',
    colorTextQuaternary: '#9c9fa5',

    // Border
    colorBorder: '#d3cec6',
    colorBorderSecondary: '#ebe7e1',

    // Shape
    borderRadius: 12,
    borderRadiusSM: 8,
    borderRadiusXS: 6,
    borderRadiusLG: 16,

    // Typography
    fontFamily:
      "'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    fontSize: 16,

    // Spacing
    padding: 16,
    paddingLG: 24,
    paddingSM: 12,
    paddingXS: 8,
    paddingXXS: 4,

    // Misc
    controlHeight: 40,
    wireframe: false,
  },
  components: {
    Button: {
      borderRadius: 8,
      borderRadiusSM: 6,
      borderRadiusLG: 12,
      controlHeight: 40,
      controlHeightLG: 48,
      controlHeightSM: 32,
      paddingInline: 16,
      paddingInlineSM: 12,
    },
    Input: {
      borderRadius: 8,
      controlHeight: 48,
      controlHeightLG: 56,
      paddingInline: 14,
      paddingBlock: 10,
    },
    Tag: {
      borderRadiusSM: 8,
    },
    Badge: {
      dotSize: 8,
    },
  },
};
