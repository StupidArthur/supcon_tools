import { useState } from "react"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { ConnectionPanel } from "@/components/ConnectionPanel"
import { SyncTab } from "@/tabs/SyncTab"
import { PublishTab } from "@/tabs/PublishTab"
import { RepublishTab } from "@/tabs/RepublishTab"

function App() {
  const [algoCount, setAlgoCount] = useState(0)

  return (
    <div className="flex flex-col h-screen p-4 gap-3 bg-gray-50">
      <ConnectionPanel onConnected={setAlgoCount} />
      <Tabs defaultValue="sync" className="flex-1 flex flex-col min-h-0">
        <TabsList className="self-start">
          <TabsTrigger value="sync">算法同步</TabsTrigger>
          <TabsTrigger value="publish">算法发布</TabsTrigger>
          <TabsTrigger value="republish">算法重发布</TabsTrigger>
        </TabsList>
        <TabsContent value="sync" className="flex-1 min-h-0">
          <SyncTab />
        </TabsContent>
        <TabsContent value="publish" className="flex-1 min-h-0">
          <PublishTab />
        </TabsContent>
        <TabsContent value="republish" className="flex-1 min-h-0">
          <RepublishTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default App
