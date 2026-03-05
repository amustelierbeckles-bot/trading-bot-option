import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Dashboard     from "./pages/Dashboard";
import Backtesting   from "./pages/Backtesting";
import Performance   from "./pages/Performance";
import ValidateMobile from "./pages/ValidateMobile";
import { Toaster }   from "./components/ui/sonner";

function App() {
  return (
    <div className="App">
      <Toaster position="top-right" />
      <BrowserRouter>
        <Routes>
          <Route path="/"            element={<Dashboard />}      />
          <Route path="/backtesting" element={<Backtesting />}    />
          <Route path="/performance" element={<Performance />}    />
          <Route path="/validate"    element={<ValidateMobile />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;