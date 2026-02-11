import React, { useState } from 'react';
import {
  AlertCircle,
  CheckCircle,
  AlertTriangle,
  ThumbsUp,
  Edit2,
  X,
  ChevronDown
} from 'lucide-react';

interface SemanticMatchReviewCardProps {
  incomingField: string;
  suggestedMatch: string | null;
  confidenceScore: number;
  schemaOptions?: string[];
  onApprove?: (field: string, match: string) => void;
  onRemap?: (field: string, newMatch: string) => void;
  onIgnore?: (field: string) => void;
}

export const SemanticMatchReviewCard: React.FC<SemanticMatchReviewCardProps> = ({
  incomingField,
  suggestedMatch,
  confidenceScore,
  schemaOptions = [],
  onApprove,
  onRemap,
  onIgnore,
}) => {
  const [isRemapping, setIsRemapping] = useState(false);
  const [remapValue, setRemapValue] = useState(suggestedMatch || '');

  // Determine confidence level based on 0.45 threshold
  const getConfidenceLevel = (score: number): 'critical' | 'warning' | 'safe' => {
    if (score < 0.45) return 'critical';
    if (score <= 0.70) return 'warning';
    return 'safe';
  };

  const confidenceLevel = getConfidenceLevel(confidenceScore);

  // Badge configuration
  const badgeConfig = {
    critical: {
      icon: AlertCircle,
      label: 'Low Confidence',
      bgColor: 'bg-red-50',
      textColor: 'text-red-700',
      borderColor: 'border-red-200',
      badgeBg: 'bg-red-100',
      badgeText: 'text-red-800',
    },
    warning: {
      icon: AlertTriangle,
      label: 'Review Needed',
      bgColor: 'bg-yellow-50',
      textColor: 'text-yellow-700',
      borderColor: 'border-yellow-200',
      badgeBg: 'bg-yellow-100',
      badgeText: 'text-yellow-800',
    },
    safe: {
      icon: CheckCircle,
      label: 'High Confidence',
      bgColor: 'bg-green-50',
      textColor: 'text-green-700',
      borderColor: 'border-green-200',
      badgeBg: 'bg-green-100',
      badgeText: 'text-green-800',
    },
  };

  const config = badgeConfig[confidenceLevel];
  const IconComponent = config.icon;

  const handleApprove = () => {
    if (suggestedMatch && onApprove) {
      onApprove(incomingField, suggestedMatch);
    }
  };

  const handleRemap = () => {
    if (remapValue && onRemap) {
      onRemap(incomingField, remapValue);
      setIsRemapping(false);
    }
  };

  const handleIgnore = () => {
    if (onIgnore) {
      onIgnore(incomingField);
    }
  };

  return (
    <div
      className={`
        ${config.bgColor} 
        ${config.borderColor}
        border rounded-lg p-4 
        transition-all duration-200 
        hover:shadow-md 
        max-w-md
      `}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1">
          <h3 className="font-semibold text-gray-900 text-sm">
            {incomingField}
          </h3>
          <p className="text-xs text-gray-600 mt-1">Incoming field name</p>
        </div>

        {/* Status Badge */}
        <div
          className={`
            ${config.badgeBg} 
            ${config.badgeText}
            px-2 py-1 
            rounded-full 
            text-xs 
            font-medium 
            flex items-center gap-1 
            ml-2 
            flex-shrink-0
          `}
        >
          <IconComponent className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">{config.label}</span>
        </div>
      </div>

      {/* Confidence Score Bar */}
      <div className="mb-4">
        <div className="flex justify-between items-center mb-1">
          <span className="text-xs font-medium text-gray-700">Confidence</span>
          <span className={`text-xs font-semibold ${config.textColor}`}>
            {(confidenceScore * 100).toFixed(0)}%
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
          <div
            className={`
              h-full transition-all duration-300 
              ${
                confidenceLevel === 'critical'
                  ? 'bg-red-500'
                  : confidenceLevel === 'warning'
                    ? 'bg-yellow-500'
                    : 'bg-green-500'
              }
            `}
            style={{ width: `${Math.min(confidenceScore * 100, 100)}%` }}
          />
        </div>
      </div>

      {/* Suggested Match Section */}
      <div className="mb-4 p-3 bg-white rounded border border-gray-200">
        <p className="text-xs text-gray-600 mb-1">Suggested Match</p>
        {suggestedMatch ? (
          <p className="text-sm font-semibold text-gray-900">
            {suggestedMatch}
          </p>
        ) : (
          <p className="text-sm text-gray-500 italic">No suggestion available</p>
        )}
      </div>

      {/* Remap Section (Conditional) */}
      {isRemapping && (
        <div className="mb-4 p-3 bg-white rounded border border-blue-200">
          <label className="text-xs text-gray-600 block mb-2 font-medium">
            Select correct field
          </label>
          {schemaOptions.length > 0 ? (
            <div className="relative mb-2">
              <select
                value={remapValue}
                onChange={(e) => setRemapValue(e.target.value)}
                className="
                  w-full px-3 py-2 
                  text-sm 
                  border border-gray-300 
                  rounded 
                  focus:outline-none 
                  focus:ring-2 
                  focus:ring-blue-500
                  appearance-none
                  bg-white
                "
              >
                <option value="">Choose a field...</option>
                {schemaOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-2.5 w-4 h-4 text-gray-400 pointer-events-none" />
            </div>
          ) : (
            <input
              type="text"
              value={remapValue}
              onChange={(e) => setRemapValue(e.target.value)}
              placeholder="Enter field name..."
              className="
                w-full px-3 py-2 
                text-sm 
                border border-gray-300 
                rounded 
                focus:outline-none 
                focus:ring-2 
                focus:ring-blue-500
                mb-2
              "
            />
          )}
          <div className="flex gap-2">
            <button
              onClick={handleRemap}
              disabled={!remapValue}
              className="
                flex-1 
                px-3 py-1.5 
                bg-blue-500 
                text-white 
                text-xs 
                font-semibold 
                rounded 
                hover:bg-blue-600 
                disabled:bg-gray-300 
                disabled:cursor-not-allowed
                transition-colors
              "
            >
              Confirm
            </button>
            <button
              onClick={() => {
                setIsRemapping(false);
                setRemapValue(suggestedMatch || '');
              }}
              className="
                flex-1 
                px-3 py-1.5 
                bg-gray-200 
                text-gray-700 
                text-xs 
                font-semibold 
                rounded 
                hover:bg-gray-300
                transition-colors
              "
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          onClick={handleApprove}
          disabled={!suggestedMatch}
          title={!suggestedMatch ? 'No suggested match available' : ''}
          className="
            flex-1 
            flex items-center justify-center gap-1.5
            px-3 py-2 
            bg-green-500 
            text-white 
            text-xs 
            font-semibold 
            rounded 
            hover:bg-green-600 
            disabled:bg-gray-300 
            disabled:cursor-not-allowed
            disabled:text-gray-500
            transition-colors
          "
        >
          <ThumbsUp className="w-4 h-4" />
          <span>Approve</span>
        </button>

        <button
          onClick={() => setIsRemapping(!isRemapping)}
          className="
            flex-1 
            flex items-center justify-center gap-1.5
            px-3 py-2 
            bg-blue-500 
            text-white 
            text-xs 
            font-semibold 
            rounded 
            hover:bg-blue-600
            transition-colors
          "
        >
          <Edit2 className="w-4 h-4" />
          <span>Remap</span>
        </button>

        <button
          onClick={handleIgnore}
          className="
            flex-1 
            flex items-center justify-center gap-1.5
            px-3 py-2 
            bg-gray-300 
            text-gray-700 
            text-xs 
            font-semibold 
            rounded 
            hover:bg-gray-400
            transition-colors
          "
        >
          <X className="w-4 h-4" />
          <span>Ignore</span>
        </button>
      </div>

      {/* Info Text */}
      <p className="text-xs text-gray-500 mt-3 text-center">
        Threshold: 0.45 | Confidence: {(confidenceScore).toFixed(2)}
      </p>
    </div>
  );
};

export default SemanticMatchReviewCard;
