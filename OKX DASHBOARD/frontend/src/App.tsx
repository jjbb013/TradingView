import React, { useEffect, useState } from 'react';
import { Table, Tag, Typography, Layout, Row, Col, Card, Menu, Button, Select, Space, Input, message, Modal } from 'antd';
import { ReloadOutlined, CheckCircleTwoTone, CloseCircleTwoTone, SendOutlined, CloseOutlined } from '@ant-design/icons';
import './App.css';

const { Title, Text } = Typography;
const { Content, Header, Sider } = Layout;

const menuItems = [
  { key: 'overview', label: 'Overview' },
  { key: 'trading', label: 'Trading Terminal' },
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
  const [activeMenu, setActiveMenu] = useState('overview');

  // Trading state
  const [tradeInstId, setTradeInstId] = useState('ETH-USDT-SWAP');
  const [tradeSize, setTradeSize] = useState('1');
  const [tradeLoading, setTradeLoading] = useState(false);

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

  const handlePlaceOrder = async (orderSide: 'buy' | 'sell') => {
    if (selectedAccount === 'all') {
      message.error('Please select a specific account to trade.');
      return;
    }
    setTradeLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/place_order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_index: Number(selectedAccount),
          inst_id: tradeInstId,
          order_size: tradeSize,
          order_side: orderSide,
        }),
      });
      const data = await res.json();
      if (data.code === '0') {
        message.success('Order placed successfully!');
      } else {
        message.error(`Order failed: ${data.msg}`);
      }
    } catch (err) {
      message.error('Failed to place order.');
    }
    setTradeLoading(false);
  };

  const handleClosePosition = (accountIndex: number, posData: PosData) => {
    Modal.confirm({
      title: 'Confirm Close Position',
      content: `Are you sure you want to close this ${posData.posSide} position on ${posData.instId}?`,
      onOk: async () => {
        try {
          const res = await fetch('http://localhost:8000/api/close_position', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_index: accountIndex, pos_data: posData }),
          });
          const data = await res.json();
          if (data.code === '0') {
            message.success('Close order sent!');
          } else {
            message.error(`Failed to close: ${data.msg}`);
          }
        } catch (err) {
          message.error('Failed to send close order.');
        }
      },
    });
  };

  const accountOptions = [
    { value: 'all', label: 'All Accounts' },
    ...Object.entries(accounts).map(([acc]) => ({
      value: acc,
      label: accountNames[Number(acc)] || `Account ${Number(acc) + 1}`
    }))
  ];

  const filteredAccounts = selectedAccount === 'all' ? accounts : { [selectedAccount]: accounts[selectedAccount] };

  const darkBg = { background: '#181c24' };
  const cardBg = { background: '#23272f', color: '#fff' };
  const textColor = { color: '#fff' };

  const renderContent = () => {
    if (activeMenu === 'trading') {
      return (
        <Card title="Trading Terminal" style={cardBg} headStyle={textColor} bordered={false}>
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Select
              value={selectedAccount}
              onChange={setSelectedAccount}
              options={accountOptions.filter(opt => opt.value !== 'all')}
              style={{ width: '100%' }}
              placeholder="Select Account"
            />
            <Input
              addonBefore="Instrument ID"
              value={tradeInstId}
              onChange={(e) => setTradeInstId(e.target.value)}
            />
            <Input
              addonBefore="Size"
              value={tradeSize}
              onChange={(e) => setTradeSize(e.target.value)}
            />
            <Space style={{ width: '100%', justifyContent: 'center' }}>
              <Button type="primary" danger onClick={() => handlePlaceOrder('sell')} loading={tradeLoading} icon={<SendOutlined />}>Sell / Short</Button>
              <Button type="primary" style={{ background: '#52c41a', borderColor: '#52c41a' }} onClick={() => handlePlaceOrder('buy')} loading={tradeLoading} icon={<SendOutlined />}>Buy / Long</Button>
            </Space>
          </Space>
        </Card>
      );
    }

    return (
      <>
        <Row gutter={[24, 24]} style={{ marginBottom: 24 }}>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Total Balance</Text>
                <Title style={{ ...textColor, margin: 0 }} level={3}>${totalBalance.toFixed(2)}</Title>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Unrealized PnL</Text>
                <Title style={{ ...textColor, margin: 0, color: totalUnrealized >= 0 ? '#52c41a' : '#ff4d4f' }} level={3}>${totalUnrealized.toFixed(2)}</Title>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Active Positions</Text>
                <Title style={{ ...textColor, margin: 0 }} level={3}>{totalActivePositions}</Title>
              </Card>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Card style={cardBg} bordered={false}>
                <Text style={{ ...textColor, fontSize: 16 }}>Last Update</Text>
                <Title style={{ ...textColor, margin: 0 }} level={3}>{lastUpdate}</Title>
              </Card>
            </Col>
        </Row>
        <Row gutter={[24, 24]}>
          {Object.entries(filteredAccounts).map(([acc, data]) => (
            <Col key={acc} xs={24} sm={24} md={12} lg={12} xl={12}>
              <div style={{ background: '#23272f', borderRadius: 8, boxShadow: '0 2px 8px #181c24', padding: 24, minHeight: 350, color: '#fff' }}>
                <Title level={4} style={{ marginBottom: 16, color: '#fff' }}>{accountNames[Number(acc)] || `Account ${Number(acc) + 1}`}</Title>
                <Typography.Text strong style={{ color: '#fff' }}>Balance:</Typography.Text>
                <Table
                  dataSource={data[0]?.balData || []}
                  columns={[
                    { title: 'Asset', dataIndex: 'ccy', key: 'ccy' },
                    { title: 'Balance', dataIndex: 'cashBal', key: 'cashBal', render: (v) => v ? Number(v).toFixed(4) : '-' },
                  ]}
                  rowKey="ccy"
                  size="small"
                  pagination={false}
                  className="dark-table"
                  style={{ marginBottom: 24 }}
                />
                <Typography.Text strong style={{ marginTop: 16, display: 'block', color: '#fff' }}>Positions:</Typography.Text>
                <Table
                  dataSource={data[0]?.posData?.filter(p => Number(p.pos) !== 0) || []}
                  columns={[
                    { title: 'InstlD', dataIndex: 'instId', key: 'instId' },
                    { title: 'Side', dataIndex: 'posSide', key: 'posSide', render: (v) => <Tag color={v === 'long' ? 'green' : 'red'}>{v.toUpperCase()}</Tag> },
                    { title: 'Pos', dataIndex: 'pos', key: 'pos' },
                    { title: 'AvgPx', dataIndex: 'avgPx', key: 'avgPx', render: (v) => v ? Number(v).toFixed(4) : '-' },
                    { title: 'LastPx', dataIndex: 'lastPrice', key: 'lastPrice', render: (v) => v ? Number(v).toFixed(4) : '-' },
                    { title: 'Unrealized PnL', dataIndex: 'unrealizedPnl', key: 'unrealizedPnl', render: (v) => <span style={{ color: v && v > 0 ? '#52c41a' : '#ff4d4f' }}>{v ? v.toFixed(2) : '-'}</span> },
                    { title: 'PnL %', dataIndex: 'unrealizedPnlPct', key: 'unrealizedPnlPct', render: (v) => <span style={{ color: v && v > 0 ? '#52c41a' : '#ff4d4f' }}>{v ? v.toFixed(2) : '-'}%</span> },
                    { title: 'Action', key: 'action', render: (_, record) => <Button size="small" danger icon={<CloseOutlined />} onClick={() => handleClosePosition(Number(acc), record)}>Close</Button> },
                  ]}
                  rowKey="instId"
                  size="small"
                  pagination={false}
                  scroll={{ x: 'max-content' }}
                  className="dark-table"
                />
              </div>
            </Col>
          ))}
        </Row>
      </>
    );
  };

  return (
    <Layout style={{ minHeight: '100vh', ...darkBg }}>
      <Header style={{ ...darkBg, borderBottom: '1px solid #222', padding: '0 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Title style={{ color: '#fff', margin: 0, lineHeight: '64px', fontSize: 24 }} level={3}>OKX Trading Monitor</Title>
        <Space>
          <span style={{ color: connected ? '#52c41a' : '#ff4d4f' }}>
            {connected ? <CheckCircleTwoTone twoToneColor="#52c41a" /> : <CloseCircleTwoTone twoToneColor="#ff4d4f" />} {connected ? 'Connected' : 'Disconnected'}
          </span>
          <Select value={selectedAccount} onChange={setSelectedAccount} options={accountOptions} style={{ width: 160 }} />
          <Button icon={<ReloadOutlined />} onClick={() => window.location.reload()}>Reconnect</Button>
        </Space>
      </Header>
      <Layout>
        <Sider width={200} style={{ ...darkBg, borderRight: '1px solid #222' }}>
          <Menu
            mode="inline"
            selectedKeys={[activeMenu]}
            onClick={({ key }) => setActiveMenu(key)}
            style={{ height: '100%', borderRight: 0, background: 'transparent' }}
            items={menuItems}
            theme="dark"
          />
        </Sider>
        <Layout style={{ padding: '24px', ...darkBg }}>
          {renderContent()}
        </Layout>
      </Layout>
    </Layout>
  );
}

export default App;