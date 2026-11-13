"""RTC transport invariants: model-space prefix, step alignment, delay, reset."""
from types import SimpleNamespace

import pytest
import torch

from lerobot.async_inference.configs import PolicyServerConfig
from lerobot.async_inference.helpers import TimedObservation
from lerobot.async_inference.policy_server import PolicyServer


class Policy:
    def __init__(self, enabled=True):
        self.config=SimpleNamespace(rtc_config=SimpleNamespace(enabled=enabled))
        self.calls=[]
        self.reset_count=0

    def predict_action_chunk(self,obs,**kwargs):
        self.calls.append(kwargs)
        return torch.arange(150.,device='cpu').reshape(1,50,3)

    def reset(self):
        self.reset_count+=1


def server(enabled=True):
    s=PolicyServer(PolicyServerConfig(fps=19.4))
    s.policy=Policy(enabled)
    s.actions_per_chunk=50
    s.last_processed_obs=TimedObservation(timestamp=1.,timestep=0,observation={})
    return s


def test_normalized_tail_next_unexecuted_and_measured_delay():
    s=server()
    chunk=s._get_action_chunk({})
    saved=chunk.clone()
    # A postprocessor may modify its input; the cached model-space prefix survives.
    chunk.add_(1000)
    s.last_processed_obs.timestep=25
    s._rtc_latency_s=.2
    s._get_action_chunk({})
    call=s.policy.calls[-1]
    assert torch.equal(call['prev_chunk_left_over'],saved[:,25:])
    assert call['inference_delay']==4
    assert s.policy.calls[0]['prev_chunk_left_over'] is None


def test_exhausted_tail_and_rtc_off():
    s=server();s._get_action_chunk({})
    s.last_processed_obs.timestep=50;s._get_action_chunk({})
    assert s.policy.calls[-1]['prev_chunk_left_over'] is None
    s.policy.config.rtc_config.enabled=False;s._get_action_chunk({})
    assert s.policy.calls[-1]=={}


def test_episode_reset_flushes_prefix_model_and_similarity_filter():
    s=server();s._get_action_chunk({});s._rtc_latency_s=.3
    s._predicted_timesteps.add(0);s.observation_queue.put(s.last_processed_obs)
    s._reset_server()
    assert s.last_processed_obs is None
    assert s._rtc_previous_chunk is None
    assert not s._predicted_timesteps
    assert s.observation_queue.empty()
    assert s._rtc_latency_s==0
    assert s.policy.reset_count==1


def test_fractional_fps_and_invalid_rate():
    assert PolicyServerConfig(fps=19.4).environment_dt==pytest.approx(1/19.4)
    with pytest.raises(ValueError):PolicyServerConfig(fps=0)
