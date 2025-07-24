import React, { useEffect, useState } from 'react';
import { Table, Tag, Typography, Layout, Row, Col, Card, Menu, Button, Select, Space } from 'antd';
import { ReloadOutlined, CheckCircleTwoTone, CloseCircleTwoTone } from '@ant-design/icons';
import './App.css';

const { Title, Text } = Typography;
const { Content, Header, Sider } = Layout;

const menuItems = [
  { key: 'overview', label: 'Overview' },
];

type BalData = {
  ccy: string;
  cashBal: string;
};
type PosData = {
  instId: string;
  instType: string;
  posSide: string;
  pos: string;
  avgPx: string;
  ccy: string;
  unrealizedPnl?: number;
  unrealizedPnlPct?: number;
  lastPrice?: number;
};
type AccountData = {
  balData: BalData[];
  posData: PosData[];
};

function App() {
  const [accounts, setAccounts] = useState<{ [k: string]: AccountData[] }>({});
  const [accountNames, setAccountNames] = useState<string[]>([]);
  const [lastUpdate, setLastUpdate] = useState<string>('Never');
  const [connected, setConnected] = useState(false);
  const [selectedAccount, setSelectedAccount] = useState<string>('all');

  // 统计数据
  const totalBalance = Object.values(accounts).reduce((sum, data) => {
    const bal = data[0]?.balData?.find(b => b.ccy === 'USDT');
    return sum + (bal ? Number(bal.cashBal) : 0);
  }, 0);
  const totalUnrealized = Object.values(accounts).reduce((sum, data) => {
    return sum + (data[0]?.posData?.reduce((s, p) => s + (p.unrealizedPnl || 0), 0) || 0);
  }, 0);
  const totalActivePositions = Object.values(accounts).reduce((sum, data) => {
    return sum + (data[0]?.posData?.filter(p => Number(p.pos) !== 0).length || 0);
  }, 0);

  useEffect(() => {
    fetch('http://localhost:8000/api/account_names')
      .then(res => res.json())
      .then(data => setAccountNames(data.account_names || []));
  }, []);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: NodeJS.Timeout | null = null;
    const connect = () => {
      ws = new WebSocket('ws://localhost:8000/ws');
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        reconnectTimer = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        setAccounts((prev) => ({
          ...prev,
          [msg.account]: msg.data,
        }));
        setLastUpdate(new Date().toLocaleTimeString());
      };
    };
    connect();
    return () => {
      ws && ws.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, []);

  // 监听窗口变化，强制刷新
  const [, setWinWidth] = useState(window.innerWidth);
  useEffect(() => {
    const onResize = () => setWinWidth(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const accountOptions = [
    { value: 'all', label: 'All Accounts' },
    ...Object.entries(accounts).map(([acc], idx) => ({
      value: acc,
      label: accountNames[Number(acc)] || `账户${Number(acc)+1}`
    }))
  ];

  const filteredAccounts = selectedAccount === 'all' ? accounts : { [selectedAccount]: accounts[selectedAccount] };

  const darkBg = { background: '#181c24' };
  const cardBg = { background: '#23272f', color: '#fff' };
  const textColor = { color: '#fff' };

  return (
    <Layout style={{ minHeight: '100vh', ...darkBg }}>
      <Header style={{ ...darkBg, borderBottom: '1px solid #222', padding: '0 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Title style={{ color: '#fff', margin: 0, lineHeight: '64px', fontSize: 24 }} level={3}>
          OKX Trading Monitor
        </Title>
        <Space>
          <span style={{ color: connected ? '#52c41a' : '#ff4d4f', fontWeight: 600 }}>
            {connected ? <CheckCircleTwoTone twoToneColor="#52c41a" /> : <CloseCircleTwoTone twoToneColor="#ff4d4f" />} Connected {Object.keys(accounts).length} accounts
          </span>
          <Select
            value={selectedAccount}
            onChange={setSelectedAccount}
            options={accountOptions}
            style={{ width: 160 }}
            size="middle"
          />
          <Button icon={<ReloadOutlined />} onClick={() => window.location.reload()} size="middle">Reconnect</Button>
        </Space>
      </Header>
      <Layout>
        <Sider width={200} style={{ ...darkBg, borderRight: '1px solid #222', minHeight: 'calc(100vh - 64px)' }}>
          <Menu
            mode="inline"
            defaultSelectedKeys={['overview']}
            style={{ height: '100%', borderRight: 0, background: 'transparent', color: '#fff' }}
            items={menuItems}
            theme="dark"
          />
        </Sider>
        <Layout style={{ padding: '24px', ...darkBg }}>
          <Row gutter={[24, 24]} style={{ marginBottom: 24 }}>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Total Balance</Text>
                <Title style={{ ...textColor, margin: 0 }} level={3}>${totalBalance.toFixed(4)}</Title>
                <Text type="secondary" style={{ color: '#52c41a' }}>Live</Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Unrealized PnL</Text>
                <Title style={{ ...textColor, margin: 0 }} level={3}>${totalUnrealized.toFixed(4)}</Title>
                <Text type="secondary" style={{ color: '#52c41a' }}>Open positions</Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Active Positions</Text>
                <Title style={{ ...textColor, margin: 0 }} level={3}>{totalActivePositions}</Title>
                <Text type="secondary" style={{ color: '#52c41a' }}>All accounts</Text>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Last Update</Text>
                <Title style={{ ...textColor, margin: 0 }} level={3}>{lastUpdate}</Title>
                <Text type="secondary" style={{ color: '#52c41a' }}>Real-time</Text>
              </Card>
            </Col>
          </Row>
          <Row gutter={[24, 24]}>
            {Object.entries(filteredAccounts).map(([acc, data], idx) => (
              <Col
                key={acc}
                xs={24}
                sm={24}
                md={12}
                lg={12}
                xl={12}
              >
                <div style={{ background: '#23272f', borderRadius: 8, boxShadow: '0 2px 8px #181c24', padding: 24, minHeight: 350, minWidth: 400, maxWidth: 700, margin: '0 auto', color: '#fff' }}>
                  <Title level={4} style={{ marginBottom: 16, color: '#fff' }}>{accountNames[Number(acc)] || `账户${Number(acc)+1}`}</Title>
                  <Typography.Text strong style={{ color: '#fff' }}>余额：</Typography.Text>
                  <div style={{ overflowX: 'auto', background: '#23272f', borderRadius: 8 }}>
                    <Table
                      dataSource={data[0]?.balData || []}
                      columns={[
                        { title: '币种', dataIndex: 'ccy', key: 'ccy' },
                        { title: '余额', dataIndex: 'cashBal', key: 'cashBal', render: (v) => v ? Number(v).toFixed(4) : '-' },
                      ]}
                      rowKey="ccy"
                      size="small"
                      pagination={false}
                      style={{ marginBottom: 24, background: '#23272f', color: '#fff' }}
                      className="dark-table"
                    />
                  </div>
                  <Typography.Text strong style={{ marginTop: 16, display: 'block', color: '#fff' }}>持仓：</Typography.Text>
                  <div style={{ overflowX: 'auto', background: '#23272f', borderRadius: 8 }}>
                    <Table
                      dataSource={data[0]?.posData || []}
                      columns={[
                        { title: '合约', dataIndex: 'instId', key: 'instId' },
                        { title: '类型', dataIndex: 'instType', key: 'instType' },
                        {
                          title: '方向',
                          dataIndex: 'posSide',
                          key: 'posSide',
                          render: (v) => <Tag color={v === 'long' ? 'green' : v === 'short' ? 'red' : 'blue'}>{v}</Tag>,
                        },
                        { title: '持仓', dataIndex: 'pos', key: 'pos' },
                        { title: '均价', dataIndex: 'avgPx', key: 'avgPx', render: (v) => v ? Number(v).toFixed(4) : '-' },
                        { title: '最新价', dataIndex: 'lastPrice', key: 'lastPrice', render: (v) => v ? Number(v).toFixed(4) : '-' },
                        { title: '币种', dataIndex: 'ccy', key: 'ccy' },
                        {
                          title: '未实现盈亏',
                          dataIndex: 'unrealizedPnl',
                          key: 'unrealizedPnl',
                          render: (v) => v === undefined ? '-' : (
                            <span style={{ color: v > 0 ? 'green' : v < 0 ? 'red' : undefined, fontWeight: 600 }}>{Number(v).toFixed(4)}</span>
                          )
                        },
                        {
                          title: '盈亏%',
                          dataIndex: 'unrealizedPnlPct',
                          key: 'unrealizedPnlPct',
                          render: (v) => v === undefined ? '-' : (
                            <span style={{ color: v > 0 ? 'green' : v < 0 ? 'red' : undefined, fontWeight: 600 }}>{Number(v).toFixed(2)}%</span>
                          )
                        },
                      ]}
                      rowKey="instId"
                      size="small"
                      pagination={false}
                      scroll={{ x: 'max-content' }}
                      style={{ minWidth: 400, background: '#23272f', color: '#fff' }}
                      className="dark-table"
                    />
                  </div>
                </div>
              </Col>
            ))}
          </Row>
        </Layout>
      </Layout>
    </Layout>
  );
}

export default App;
