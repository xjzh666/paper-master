import { Layout, Typography } from 'antd'

const { Sider, Content } = Layout

export default function App() {
  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={320} theme="light" style={{ borderRight: '1px solid #eee' }}>
        <Typography.Title level={5} style={{ padding: 12 }}>Zotero 论文库</Typography.Title>
      </Sider>
      <Content style={{ padding: 16, borderRight: '1px solid #eee' }}>
        <Typography.Title level={5}>对话</Typography.Title>
      </Content>
      <Sider width={560} theme="light" style={{ padding: 16, overflow: 'auto' }}>
        <Typography.Title level={5}>阅读</Typography.Title>
      </Sider>
    </Layout>
  )
}
