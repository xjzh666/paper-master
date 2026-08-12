import { Layout } from 'antd'
import PaperListSidebar from './components/PaperListSidebar'
import ReadingPanel from './components/ReadingPanel'

const { Sider, Content } = Layout

export default function App() {
  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={320} theme="light" style={{ borderRight: '1px solid #eee' }}>
        <PaperListSidebar onOpen={(item) => console.log('open', item.title)} />
      </Sider>
      <Content style={{ padding: 16, borderRight: '1px solid #eee' }}>对话</Content>
      <Sider width={560} theme="light" style={{ padding: 16, overflow: 'auto' }}>
        <ReadingPanel status="idle" error="" overview={null} markdown="" />
      </Sider>
    </Layout>
  )
}
