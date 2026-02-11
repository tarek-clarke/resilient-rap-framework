/**
 * Semantic Match Review Card - Usage Examples
 * 
 * This file demonstrates how to use the SemanticMatchReviewCard component
 * in a real-world human-in-the-loop telemetry pipeline review system.
 */

import React, { useState } from 'react';
import SemanticMatchReviewCard from './SemanticMatchReviewCard';

// Example schema for different domains
const STANDARD_SCHEMA = [
  'Heart Rate (bpm)',
  'Brake Temperature (Celsius)',
  'Tire Pressure (psi)',
  'Vehicle Speed (km/h)',
  'Engine RPM',
  'Steering Angle (degrees)',
  'Throttle Position (%)',
  'Acceleration (g)',
  'DRS Status',
  'Fuel Load (kg)',
];

// Example telemetry field reviews based on benchmark data
const EXAMPLE_REVIEWS = [
  {
    id: 1,
    incomingField: 'hr_watch_01',
    suggestedMatch: 'Heart Rate (bpm)',
    confidenceScore: 0.85,
    status: 'safe',
    description: 'High confidence match - biometric watch naming convention',
  },
  {
    id: 2,
    incomingField: 'brk_tmp_fr',
    suggestedMatch: null,
    confidenceScore: 0.20,
    status: 'critical',
    description: 'Low confidence - heavily abbreviated, no suggestion',
  },
  {
    id: 3,
    incomingField: 'tyre_press_fl',
    suggestedMatch: 'Tire Pressure (psi)',
    confidenceScore: 0.42,
    status: 'critical',
    description: 'Just below threshold - British spelling with positional notation',
  },
  {
    id: 4,
    incomingField: 'car_velocity',
    suggestedMatch: 'Vehicle Speed (km/h)',
    confidenceScore: 0.65,
    status: 'warning',
    description: 'Needs review - alternative terminology',
  },
  {
    id: 5,
    incomingField: 'eng_rpm_log',
    suggestedMatch: 'Engine RPM',
    confidenceScore: 0.62,
    status: 'warning',
    description: 'Needs review - logging suffix attached',
  },
  {
    id: 6,
    incomingField: 'steering_angle_weird',
    suggestedMatch: 'Steering Angle (degrees)',
    confidenceScore: 0.79,
    status: 'safe',
    description: 'High confidence despite typo in name',
  },
];

/**
 * Dashboard Example: Reviews Grid
 * Shows how to display multiple cards in a human-in-the-loop dashboard
 */
export const SemanticReviewDashboard: React.FC = () => {
  const [reviews, setReviews] = useState(EXAMPLE_REVIEWS);
  const [stats, setStats] = useState({
    total: EXAMPLE_REVIEWS.length,
    approved: 0,
    ignored: 0,
    pending: EXAMPLE_REVIEWS.length,
  });

  const handleApprove = (fieldName: string, match: string) => {
    console.log(`✓ Approved: ${fieldName} → ${match}`);
    setReviews((prev) =>
      prev.filter((review) => review.incomingField !== fieldName)
    );
    setStats((prev) => ({
      ...prev,
      approved: prev.approved + 1,
      pending: prev.pending - 1,
    }));
  };

  const handleRemap = (fieldName: string, newMatch: string) => {
    console.log(`↻ Remapped: ${fieldName} → ${newMatch}`);
    setReviews((prev) =>
      prev.filter((review) => review.incomingField !== fieldName)
    );
    setStats((prev) => ({
      ...prev,
      approved: prev.approved + 1,
      pending: prev.pending - 1,
    }));
  };

  const handleIgnore = (fieldName: string) => {
    console.log(`✗ Ignored: ${fieldName}`);
    setReviews((prev) =>
      prev.filter((review) => review.incomingField !== fieldName)
    );
    setStats((prev) => ({
      ...prev,
      ignored: prev.ignored + 1,
      pending: prev.pending - 1,
    }));
  };

  const completionPercentage = Math.round(
    ((stats.approved + stats.ignored) / stats.total) * 100
  );

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {/* Header */}
      <div className="max-w-7xl mx-auto mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          Semantic Match Review
        </h1>
        <p className="text-gray-600">
          Review and approve AI-suggested field name mappings for your telemetry pipeline
        </p>
      </div>

      {/* Stats Bar */}
      <div className="max-w-7xl mx-auto mb-8">
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <p className="text-sm text-gray-600">Total Fields</p>
            <p className="text-2xl font-bold text-gray-900">{stats.total}</p>
          </div>
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <p className="text-sm text-gray-600">Approved</p>
            <p className="text-2xl font-bold text-green-600">{stats.approved}</p>
          </div>
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <p className="text-sm text-gray-600">Ignored</p>
            <p className="text-2xl font-bold text-gray-600">{stats.ignored}</p>
          </div>
          <div className="bg-white p-4 rounded-lg border border-gray-200">
            <p className="text-sm text-gray-600">Pending</p>
            <p className="text-2xl font-bold text-blue-600">{stats.pending}</p>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="mt-4 bg-white p-4 rounded-lg border border-gray-200">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium text-gray-700">Overall Progress</span>
            <span className="text-sm font-semibold text-gray-900">
              {completionPercentage}%
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
            <div
              className="h-full bg-green-500 transition-all duration-300"
              style={{ width: `${completionPercentage}%` }}
            />
          </div>
        </div>
      </div>

      {/* Cards Grid */}
      <div className="max-w-7xl mx-auto">
        {reviews.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {reviews.map((review) => (
              <div key={review.id} className="relative">
                <SemanticMatchReviewCard
                  incomingField={review.incomingField}
                  suggestedMatch={review.suggestedMatch}
                  confidenceScore={review.confidenceScore}
                  schemaOptions={STANDARD_SCHEMA}
                  onApprove={handleApprove}
                  onRemap={handleRemap}
                  onIgnore={handleIgnore}
                />
                {/* Debug Info - Remove in production */}
                <div className="mt-2 text-xs text-gray-500 text-center">
                  {review.description}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
            <h3 className="text-lg font-semibold text-gray-900 mb-2">
              🎉 All reviews complete!
            </h3>
            <p className="text-gray-600">
              {stats.approved} approved, {stats.ignored} ignored
            </p>
          </div>
        )}
      </div>

      {/* Threshold Info */}
      <div className="max-w-7xl mx-auto mt-8 p-4 bg-blue-50 border border-blue-200 rounded-lg">
        <h3 className="font-semibold text-blue-900 mb-2">Confidence Thresholds</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm text-blue-800">
          <div>
            <span className="font-semibold">🔴 Critical (< 0.45):</span> Low confidence,
            likely obscure abbreviations
          </div>
          <div>
            <span className="font-semibold">🟡 Warning (0.45 - 0.70):</span> Review
            needed, check suggestions
          </div>
          <div>
            <span className="font-semibold">🟢 Safe (> 0.70):</span> High confidence,
            auto-approve safe
          </div>
        </div>
      </div>
    </div>
  );
};

/**
 * Standalone Card Example
 * Shows a single card with full interactivity
 */
export const StandaloneCardExample: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-50 p-8 flex items-center justify-center">
      <div className="w-full max-w-md">
        <SemanticMatchReviewCard
          incomingField="brk_tmp_fr"
          suggestedMatch="Brake Temperature (Celsius)"
          confidenceScore={0.65}
          schemaOptions={STANDARD_SCHEMA}
          onApprove={(field, match) =>
            console.log(`Approved: ${field} → ${match}`)
          }
          onRemap={(field, match) =>
            console.log(`Remapped: ${field} → ${match}`)
          }
          onIgnore={(field) => console.log(`Ignored: ${field}`)}
        />
      </div>
    </div>
  );
};

export default SemanticReviewDashboard;
