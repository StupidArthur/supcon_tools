import Toolbar from './components/Toolbar'
import ParamPanel from './components/ParamPanel'
import ChartPanel from './components/ChartPanel'
import StatusBar from './components/StatusBar'

function App() {
  return (
    <div className="h-screen flex flex-col bg-gray-900 text-gray-100">
      <Toolbar />
      <div className="flex-1 flex min-h-0">
        <ParamPanel />
        <ChartPanel />
      </div>
      <StatusBar />
    </div>
  )
}

export default App
