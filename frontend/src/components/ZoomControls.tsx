import { ZoomIn, ZoomOut, Maximize, RotateCcw } from 'lucide-react';
import { useReactFlow } from '@xyflow/react';

export default function ZoomControls() {
  const { zoomIn, zoomOut, fitView, setViewport } = useReactFlow();

  const resetZoom = () => {
    setViewport({ x: 0, y: 0, zoom: 1 }, { duration: 300 });
  };

  return (
    <div className="absolute bottom-4 left-4 flex flex-col gap-1 bg-white/90 backdrop-blur shadow-md rounded-lg p-1 z-10 border border-gray-200">
      <button
        onClick={() => zoomIn({ duration: 300 })}
        className="p-2 hover:bg-gray-100 rounded transition-colors"
        title="Zoom In"
      >
        <ZoomIn size={16} className="text-gray-600" />
      </button>
      <button
        onClick={() => zoomOut({ duration: 300 })}
        className="p-2 hover:bg-gray-100 rounded transition-colors"
        title="Zoom Out"
      >
        <ZoomOut size={16} className="text-gray-600" />
      </button>
      <div className="w-full h-px bg-gray-200 my-0.5" />
      <button
        onClick={() => fitView({ padding: 0.2, duration: 300 })}
        className="p-2 hover:bg-gray-100 rounded transition-colors"
        title="Fit View"
      >
        <Maximize size={16} className="text-gray-600" />
      </button>
      <button
        onClick={resetZoom}
        className="p-2 hover:bg-gray-100 rounded transition-colors"
        title="Reset Zoom"
      >
        <RotateCcw size={16} className="text-gray-600" />
      </button>
    </div>
  );
}
