import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import CriticalPerformancePanel from '../CriticalPerformancePanel';
import axios from 'axios';

// Mock de axios
jest.mock('axios');

describe('CriticalPerformancePanel Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renderiza el título y placeholders iniciales', () => {
    render(<CriticalPerformancePanel />);
    
    // Verifica que el título estático esté presente
    expect(screen.getByText(/Aparato Crítico/i)).toBeInTheDocument();
    
    // Verifica que inicialmente los valores sean guiones o placeholders
    // Buscamos elementos que contengan "—"
    const placeholders = screen.getAllByText(/—/i);
    expect(placeholders.length).toBeGreaterThan(0);
  });

  test('muestra sessionWinRate desde props correctamente', () => {
    // Pasamos un Win Rate del 75%
    render(<CriticalPerformancePanel sessionWinRate={75} />);
    
    // Debería mostrar "75%"
    expect(screen.getByText('75%')).toBeInTheDocument();
    
    // Y el texto humano correspondiente a > 60%
    expect(screen.getByText(/Eficiencia actual de la estrategia \(Objetivo >60%\) ✓/i)).toBeInTheDocument();
  });

  test('muestra datos de la API (mockeados)', async () => {
    // Simulamos respuesta de la API para /api/trades/stats
    const mockStats = {
      win_rate: 65,
      profit_factor: 1.5
    };
    
    axios.get.mockImplementation((url) => {
      if (url.includes('/api/trades/stats')) {
        return Promise.resolve({ data: mockStats });
      }
      return Promise.resolve({ data: {} });
    });

    render(<CriticalPerformancePanel />);

    // Esperamos a que el Profit Factor se actualice (1.50)
    await waitFor(() => {
        // Usamos una función matcher más flexible para encontrar "1.50"
        expect(screen.getByText((content, element) => {
            return content.includes('1.50');
        })).toBeInTheDocument();
    });

    // Verificamos el texto humano para PF >= 1.3
    expect(screen.getByText(/Relación de ganancia vs pérdida \(Salud de la cuenta\) ✓/i)).toBeInTheDocument();
  });
});
