from Box2D.b2 import world
from Box2D import (b2CircleShape, b2FixtureDef, b2LoopShape, b2PolygonShape,
                   b2_dynamicBody, b2_staticBody, b2Filter, b2Vec2)
import numpy as np


class AirHockeyBox2D:
    def __init__(self,
                 num_paddles, 
                 num_pucks, 
                 num_blocks, 
                 num_obstacles, 
                 num_targets, 
                 absorb_target, 
                 length, 
                 width,
                 puck_radius, 
                 paddle_radius, 
                 block_width,
                 max_force_timestep, 
                 force_scaling, 
                 paddle_damping, 
                 puck_damping,
                 render_size, 
                 render_masks=False, 
                 gravity=-5,
                 paddle_density=1000,
                 puck_density=250,
                 block_density=1000,
                 max_paddle_vel=2,
                 time_frequency=20):

        # task specific params
        self.num_pucks = num_pucks
        self.multiagent = num_paddles > 1
        self.num_blocks = num_blocks
        self.num_obstacles = num_obstacles
        self.num_targets = num_targets
        
        # physics / world params
        self.length, self.width = length, width
        self.num_paddles = num_paddles
        self.paddle_radius = paddle_radius
        self.puck_radius = puck_radius
        self.block_width = block_width  
        self.max_force_timestep = max_force_timestep
        self.time_frequency = time_frequency
        self.time_per_step = 1 / self.time_frequency
        self.force_scaling = force_scaling
        self.absorb_target = absorb_target
        self.paddle_damping = paddle_damping
        self.puck_damping = puck_damping
        self.gravity = gravity
        self.puck_min_height = (-length / 2) + (length / 3)
        self.paddle_max_height = 0
        self.block_min_height = 0
        self.max_speed_start = width
        self.min_speed_start = -width
        self.paddle_density = paddle_density
        self.puck_density = puck_density
        self.block_density = block_density
        # these assume 2d, in 3d since we have height it would be higher mass
        self.paddle_mass = self.paddle_density * np.pi * self.paddle_radius ** 2
        self.puck_mass = self.puck_density * np.pi * self.puck_radius ** 2

        # these 2 will depend on the other parameters
        self.max_paddle_vel = max_paddle_vel # m/s. This will be dependent on the robot arm
        # compute maximum force based on max paddle velocity
        max_a = self.max_paddle_vel / self.time_per_step
        max_f = self.paddle_mass * max_a
        # assume maximum force transfer
        puck_max_a = max_f / self.puck_mass
        self.max_puck_vel = puck_max_a * self.time_per_step
        self.world = world(gravity=(0, self.gravity), doSleep=True) # gravity is negative usually

        # box2d visualization params (but the visualization is done in the Render file)
        self.ppm = render_size / self.width
        self.render_width = int(render_size)
        self.render_length = int(self.ppm * self.length)
        self.render_masks = render_masks
        
        self.table_x_min = -self.width / 2
        self.table_x_max = self.width / 2
        self.table_y_min = -self.length / 2
        self.table_y_max = self.length / 2
        
        self.min_goal_radius = self.width / 16
        self.max_goal_radius = self.width / 4
        
        self.metadata = {}
        
        # creating the ground -- need to only call once! otherwise it can be laggy
        self.ground_body = self.world.CreateBody(
            shapes=b2LoopShape(vertices=[(self.table_x_min, self.table_y_min),
                                         (self.table_x_min, self.table_y_max), 
                                         (self.table_x_max, self.table_y_max),
                                         (self.table_x_max, self.table_y_min)]),
        )
        self.reset()

    @staticmethod
    def from_dict(state_dict):
        return AirHockeyBox2D(**state_dict)

    def reset(self, 
              seed=None, 
              ego_goal_pos=None,
              alt_goal_pos=None,
              object_state_dict=None, 
              type_instance_dict=None, 
              max_count_dict=None):

        if seed is None:
            seed = np.random.randint(10e8)
        np.random.seed(seed)

        if hasattr(self, "object_dict"):
            for body in self.object_dict.values():
                self.world.DestroyBody(body)

        if type(self.gravity) == list:
            self.world.gravity = (0, np.random.uniform(low=self.gravity[0], high=self.gravity[1]))

        self.paddles = dict()
        self.pucks = dict()
        self.blocks = dict()
        self.obstacles = dict()
        self.targets = dict()

        self.paddle_attrs = None
        self.target_attrs = None

        self.create_world_objects()
        state_info = self.get_current_state()
        return state_info
    
    def convert_from_box2d_coords(self, state_info):
        # traverse through state_info until we find tuple, then correct
        for key, value in state_info.items():
            if type(value) == list:
                for i in range(len(value)):
                    for key2, value2 in value[i].items():
                        if type(value2) == tuple:
                            state_info[key][i][key2] = (-value2[1], value2[0])
            else:
                for key2, value2 in value.items():
                    for key3, value3 in value2.items():
                        state_info[key][key2][key3] = (-value3[1], value3[0])
        return state_info

    def get_current_state(self):

        state_info = {}
        
        ego_paddle_x_pos = self.paddles['paddle_ego'][0].position[0]
        ego_paddle_y_pos = self.paddles['paddle_ego'][0].position[1]
        ego_paddle_x_vel = self.paddles['paddle_ego'][0].linearVelocity[0]
        ego_paddle_y_vel = self.paddles['paddle_ego'][0].linearVelocity[1]
        
        state_info['paddles'] = {'paddle_ego': {'position': (ego_paddle_x_pos, ego_paddle_y_pos),
                                            'velocity': (ego_paddle_x_vel, ego_paddle_y_vel)}}

        puck_x_pos = self.pucks[self.puck_names[0]][0].position[0]
        puck_y_pos = self.pucks[self.puck_names[0]][0].position[1]
        puck_x_vel = self.pucks[self.puck_names[0]][0].linearVelocity[0]
        puck_y_vel = self.pucks[self.puck_names[0]][0].linearVelocity[1]
        
        pucks_info = []
        for puck_name in self.puck_names:
            puck_x_pos = self.pucks[puck_name][0].position[0]
            puck_y_pos = self.pucks[puck_name][0].position[1]
            puck_x_vel = self.pucks[puck_name][0].linearVelocity[0]
            puck_y_vel = self.pucks[puck_name][0].linearVelocity[1]
            pucks_info.append({'position': (puck_x_pos, puck_y_pos), 
                               'velocity': (puck_x_vel, puck_y_vel)})
        
        state_info['pucks'] = pucks_info
        return self.convert_from_box2d_coords(state_info)

    def create_world_objects(self):
        for i in range(self.num_pucks):
            name, puck_attrs = self.create_puck(i, min_height=self.puck_min_height)
            self.pucks[name] = puck_attrs

        for i in range(self.num_blocks):
            name, block_attrs = self.create_block_type(i, name_type = "Block", dynamic=False, min_height = self.block_min_height)
            self.blocks[name] = block_attrs

        for i in range(self.num_obstacles): # could replace with arbitary polygons
            name, obs_attrs = self.create_block_type(i, name_type = "Obstacle", angle=np.random.rand() * np.pi, dynamic = False, color=(0, 127, 127), min_height = self.block_min_height)
            self.obstacles[name] = obs_attrs

        for i in range(self.num_targets):
            name, target_attrs = self.create_block_type(i, name_type = "Target", color=(255, 255, 0))
            self.targets[name] = target_attrs
        
        name, paddle_attrs = self.create_paddle(i, name="paddle_ego", color=(0, 255, 0))
        self.paddles[name] = paddle_attrs

        if self.multiagent:
            name_alt, paddle_alt_attrs = self.create_paddle(i=i, name="paddle_alt", color=(0, 255, 0), home_paddle=False)
            self.paddles[name_alt] = paddle_alt_attrs

        # names and object dict
        self.puck_names = list(self.pucks.keys())
        self.puck_names.sort()
        self.paddle_names = list(self.paddles.keys())
        self.block_names = list(self.blocks.keys())
        self.block_names.sort()
        self.obstacle_names = list(self.obstacles.keys())
        self.obstacle_names.sort()
        self.target_names = list(self.targets.keys())
        self.target_names.sort()
        self.object_dict = {**{name: self.pucks[name][0] for name in self.pucks.keys()},
                            **{name: self.paddles[name][0] for name in self.paddles.keys()},
                             **{name: self.blocks[name][0] for name in self.blocks.keys()},
                             **{name: self.targets[name][0] for name in self.targets.keys()},
                             **{name: self.obstacles[name][0] for name in self.obstacles.keys()},
                             }

    def create_paddle(self, i, 
                        name=None, 
                        color=(127, 127, 127), 
                        vel=None, 
                        pos=None, 
                        collidable=True, 
                        home_paddle=True):
        if not self.multiagent:
            if pos is None:
                pos = (0, -self.length / 2 + 0.01) # start at home region
            # below code is for a random position
            # if pos is None: pos = ((np.random.rand() - 0.5) * 2 * (self.table_x_max), 
            #                        max(min_height,-self.length / 2) + (np.random.rand() * ((min(max_height,self.length / 2)) - (max(min_height,-self.length / 2)))))
        else:
            if pos is None: 
                if home_paddle:
                    pos = (0, -self.length / 2 + 0.01)
                else:
                    pos = (0, self.length / 2 - 0.01)
                    
        if vel is None: 
            vel = (np.random.rand() * (self.max_speed_start - self.min_speed_start) + self.min_speed_start,
                   np.random.rand() * (self.max_speed_start - self.min_speed_start) + self.min_speed_start)
        radius = self.paddle_radius
        paddle = self.world.CreateDynamicBody(
            fixtures=b2FixtureDef(
                shape=b2CircleShape(radius=radius),
                density=self.paddle_density,
                restitution = 1.0,
                filter=b2Filter (maskBits=1,
                                 categoryBits=1 if collidable else 0)),
            bullet=True,
            position=pos,
            linearDamping=self.paddle_damping
        )
        color =  color # randomize color
        default_paddle_name = "paddle" + str(i)
        paddle.gravityScale = 0
        return ((default_paddle_name, (paddle, color)) if name is None else (name, (paddle, color)))

    # puck = bouncing ball
    def create_puck(self, i, 
                        name=None, 
                        color=(127, 127, 127), 
                        radius=-1,
                        vel=None, 
                        pos=None, 
                        collidable=True,
                        min_height=-30,
                        max_height=30):
        if not self.multiagent:
            # then we want it to start at the top, which is max_height, 0
            if pos is None: 
                x_pos = np.random.uniform(low=-self.width / 3, high=self.width / 3) # doesnt spawn at edges
                # (np.random.rand() - 0.5) * 2 * (self.table_x_max)
                pos = (x_pos,
                       min(max_height, self.length / 2) - 0.01)
        else: 
            if pos is None: 
                pos = ((np.random.rand() - 0.5) * 2 * (self.table_x_max), 
                       max(min_height,-self.length / 2) + (np.random.rand() * ((min(max_height,self.length / 2)) - (max(min_height,-self.length / 2)))))
        # print(name, pos, min_height, max_height)
        if not self.multiagent:
            if vel is None: 
                vel = (2 * np.random.rand() * (self.max_speed_start - self.min_speed_start) + self.min_speed_start,
                       -0.7)
                # with 1/4th p, add x vel
                if np.random.rand() < 0.25:
                    # vel = (2 * np.random.rand() * (self.max_speed_start - self.min_speed_start) + self.min_speed_start, -1)
                    vel = (0, -1)
                else:
                    vel = (0, -1)
        else:
            if vel is None: 
                vel = (np.random.rand() * (self.max_speed_start - self.min_speed_start) + self.min_speed_start,
                       10 * np.random.rand() * (self.max_speed_start - self.min_speed_start) + self.min_speed_start)
        if radius < 0: 
            # radius = max(1, np.random.rand() * (self.width/ 2))
            # radius = self.width / 5.325
            radius = self.puck_radius
        puck = self.world.CreateDynamicBody(
            fixtures=b2FixtureDef(
                shape=b2CircleShape(radius=radius),
                density=self.puck_density,
                restitution = 1.0,
                filter=b2Filter (maskBits=1,
                                 categoryBits=1 if collidable else 0)),
            bullet=True,
            position=pos,
            linearVelocity=vel,
            linearDamping=self.puck_damping
        )
        color =  color # randomize color
        puck_name = "puck" + str(i)
        return ((puck_name, (puck, color)) if name is None else (name, (puck, color)))

    def create_block_type(self, i, name=None,name_type=None, color=(127, 127, 127), width=-1, height=-1, vel=None, pos=None, dynamic=True, angle=0, angular_vel=0, fixed_rotation=False, collidable=True, min_height=-30):
        if pos is None: pos = ((np.random.rand() - 0.5) * 2 * (self.table_x_max), min_height + (np.random.rand() * (self.length - (min_height + self.length / 2))))
        if vel is None: vel = ((np.random.rand() - 0.5) * 2 * (self.width),(np.random.rand() - 0.5) * 2 * (self.length))
        if not dynamic: vel = np.zeros((2,))
        if width < 0: width = max(0.75, np.random.rand() * 3)
        if height < 0: height = max(0.5, np.random.rand())
        # TODO: possibly create obstacles of arbitrary shape
        vertices = [([-width / 2, -height / 2]), ([width / 2, -height / 2]), ([width / 2, height / 2]), ([-width / 2, height / 2])]
        block_name  = name_type # Block, Obstacle, Target

        fixture = b2FixtureDef(
            shape=b2PolygonShape(vertices=vertices),
            density=self.block_density,
            restitution=0.1,
            filter=b2Filter (maskBits=1,
                                 categoryBits=1 if collidable else 0),
        )

        body = self.world.CreateBody(type=b2_dynamicBody if dynamic else b2_staticBody,
                                    position=pos,
                                    linearVelocity=vel,
                                    angularVelocity=angular_vel,
                                    angle=angle,
                                    fixtures=fixture,
                                    fixedRotation=fixed_rotation,
                                    )
        color =  color # randomize color
        block_name = block_name + str(i)
        return (block_name if name is None else name), (body, color)
    
    def convert_to_box2d_coords(self, action):
        action = np.array((action[1], -action[0]))
        return action

    # s, a -> s'
    def get_transition(self, action, other_action=None):
        if self.multiagent:
            return self.get_multiagent_transition(action, other_action)
        else:
            action = self.convert_to_box2d_coords(action)
            return self.get_singleagent_transition(action)

    def get_singleagent_transition(self, action):
        
        # check if out of bounds and correct
        pos = [self.paddles['paddle_ego'][0].position[0], self.paddles['paddle_ego'][0].position[1]]
        if pos[1] > 0 - 3 * self.paddle_radius:
            action[1] = min(action[1], 0)
        
        # action is delta position
        # let's use simple time-optimal control to figure out the force to apply
        delta_pos = np.array([action[0], action[1]])
        # if delta_pos[0] == 0 and delta_pos[1] == 0:
        #     force = np.array([0, 0])
        # else:
        current_vel = np.array([self.paddles['paddle_ego'][0].linearVelocity[0], self.paddles['paddle_ego'][0].linearVelocity[1]])
        accel = [2 * (delta_pos[0] - current_vel[0] * self.time_per_step) / self.time_per_step ** 2,
                2 * (delta_pos[1] - current_vel[1] * self.time_per_step) / self.time_per_step ** 2]
        # force = np.array([self.paddles['paddle_ego'][0].mass * accel[0], self.paddles['paddle_ego'][0].mass * accel[1]])
        
        # # first let's determine velocity
        vel = delta_pos / self.time_per_step
        vel_mag = np.linalg.norm(vel)
        vel_unit = vel / (vel_mag + 1e-8)

        if vel_mag > self.max_paddle_vel:
            vel = vel_unit * self.max_paddle_vel

        force = self.paddles['paddle_ego'][0].mass * vel / self.time_per_step
        force_mag = np.linalg.norm(force)
        force_unit = force / (force_mag + 1e-8)
        if force_mag > self.max_force_timestep:
            force = force_unit * self.max_force_timestep
            
        force = force.astype(float)
        if self.paddles['paddle_ego'][0].position[1] > 0: 
            new_force = self.force_scaling * self.paddles['paddle_ego'][0].mass * action[1]
            if new_force < -self.max_force_timestep:
                new_force = -self.max_force_timestep
            force[1] = min(new_force, 0)
        if 'paddle_ego' in self.paddles:
            self.paddles['paddle_ego'][0].ApplyForceToCenter(force, True)

        # pos = [self.paddles['paddle_ego'][0].position[0], self.paddles['paddle_ego'][0].position[1]]
        # new_pos = [pos[0] + vel[0] * self.time_per_step, pos[1] + vel[1] * self.time_per_step]
        # # new_pos should be within the board though
        # if new_pos[0] < self.table_x_min:
        #     new_pos[0] = self.table_x_min
        # if new_pos[0] > self.table_x_max:
        #     new_pos[0] = self.table_x_max
        # if new_pos[1] < self.table_y_min:
        #     new_pos[1] = self.table_y_min
        # if new_pos[1] > self.table_y_max:
        #     new_pos[1] = self.table_y_max

        # # calculate what new vel will be after applying force
        # accel = [force[0] / self.paddles['paddle_ego'][0].mass, force[1] / self.paddles['paddle_ego'][0].mass]
        # new_vel = [vel[0] + accel[0] * self.time_per_step, vel[1] + accel[1] * self.time_per_step]
        # new_pos = [pos[0] + vel[0] * self.time_per_step + 0.5 * accel[0] * self.time_per_step ** 2, 
        #            pos[1] + vel[1] * self.time_per_step + 0.5 * accel[1] * self.time_per_step ** 2]
        
        # print('\n')
        # print('action', action)
        
        # print("velocity_before", self.paddles['paddle_ego'][0].linearVelocity)
        # print('position before', self.paddles['paddle_ego'][0].position)

        self.world.Step(self.time_per_step, 10, 10)
        
        # print("velocity after", self.paddles['paddle_ego'][0].linearVelocity)
        # print('position after', self.paddles['paddle_ego'][0].position)
        # print('predicted new vel', new_vel)
        # print('predicted new pos', new_pos)

        
        # self.paddles['paddle_ego'][0].linearVelocity = b2Vec2(vel[0], vel[1])
        # self.paddles['paddle_ego'][0].position = (new_pos[0], new_pos[1])
        
        vel = np.array([self.paddles['paddle_ego'][0].linearVelocity[0], self.paddles['paddle_ego'][0].linearVelocity[1]])
        vel_mag = np.linalg.norm(vel)

        # keep velocity at a maximum value
        if vel_mag > self.max_paddle_vel:
            self.paddles['paddle_ego'][0].linearVelocity = b2Vec2(vel[0] / vel_mag * self.max_paddle_vel, vel[1] / vel_mag * self.max_paddle_vel)
            
        # check if out of bounds and correct
        pos = [self.paddles['paddle_ego'][0].position[0], self.paddles['paddle_ego'][0].position[1]]
        if pos[0] < self.table_x_min:
            pos[0] = self.table_x_min
        if pos[0] > self.table_x_max:
            pos[0] = self.table_x_max
        if pos[1] > 0:
            pos[1] = 0
        if pos[1] > self.table_y_max:
            pos[1] = self.table_y_max
        self.paddles['paddle_ego'][0].position = (pos[0], pos[1])
        
        state_info = self.get_current_state()
        return state_info
    
    def get_multiagent_transition(self, joint_action):
        action_ego, action_alt = joint_action
        ego_delta_pos = np.array([action_ego[0], action_ego[1]])
        alt_delta_pos = np.array([action_alt[0], action_alt[1]])
        
        # first let's determine velocity
        ego_vel = ego_delta_pos / self.time_per_step
        alt_vel = alt_delta_pos / self.time_per_step
        ego_vel_mag = np.linalg.norm(ego_vel)
        alt_vel_mag = np.linalg.norm(alt_vel)
        ego_vel_unit = ego_vel / (ego_vel_mag + 1e-8)
        alt_vel_unit = alt_vel / (alt_vel_mag + 1e-8)
        
        if ego_vel_mag > self.max_paddle_vel:
            ego_vel = ego_vel_unit * self.max_paddle_vel
        if alt_vel_mag > self.max_paddle_vel:
            alt_vel = alt_vel_unit * self.max_paddle_vel
            
        force_ego = self.paddles['paddle_ego'][0].mass * ego_vel / self.time_per_step
        force_alt = self.paddles['paddle_alt'][0].mass * alt_vel / self.time_per_step
        force_mag_ego = np.linalg.norm(force_ego)
        force_mag_alt = np.linalg.norm(force_alt)
        force_unit_ego = force_ego / (force_mag_ego + 1e-8)
        force_unit_alt = force_alt / (force_mag_alt + 1e-8)
        
        if force_mag_ego > self.max_force_timestep:
            force_ego = force_unit_ego * self.max_force_timestep
            
        if force_mag_alt > self.max_force_timestep:
            force_alt = force_unit_alt * self.max_force_timestep
            
        force_ego = force_ego.astype(float)
        force_alt = force_alt.astype(float)
        
        if self.paddles['paddle_ego'][0].position[1] > 0:
            force_ego[1] = min(self.force_scaling * self.paddles['paddle_ego'][0].mass * action_ego[1], 0)
        if self.paddles['paddle_alt'][0].position[1] < 0:
            force_alt[1] = min(self.force_scaling * self.paddles['paddle_alt'][0].mass * action_alt[1], 0)
        if 'paddle_ego' in self.paddles:
            self.paddles['paddle_ego'][0].ApplyForceToCenter(force_ego, True)
        if 'paddle_alt' in self.paddles:
            self.paddles['paddle_alt'][0].ApplyForceToCenter(force_alt, True)
            
        vel_ego = np.array([self.paddles['paddle_ego'][0].linearVelocity[0], self.paddles['paddle_ego'][0].linearVelocity[1]])
        vel_alt = np.array([self.paddles['paddle_alt'][0].linearVelocity[0], self.paddles['paddle_alt'][0].linearVelocity[1]])
        vel_mag_ego = np.linalg.norm(vel_ego)
        vel_mag_alt = np.linalg.norm(vel_alt)
        
        pos_ego = [self.paddles['paddle_ego'][0].position[0], self.paddles['paddle_ego'][0].position[1]]
        new_pos_ego = [pos_ego[0] + vel_ego[0] * self.time_per_step, pos_ego[1] + vel_ego[1] * self.time_per_step]
        
        pos_alt = [self.paddles['paddle_alt'][0].position[0], self.paddles['paddle_alt'][0].position[1]]
        new_pos_alt = [pos_alt[0] + vel_alt[0] * self.time_per_step, pos_alt[1] + vel_alt[1] * self.time_per_step]
        
        # new_pos should be within the board though
        if pos_ego[0] < self.table_x_min:
            pos_ego[0] = self.table_x_min
        if pos_ego[0] > self.table_x_max:
            pos_ego[0] = self.table_x_max
        if pos_ego[1] < self.table_y_min:
            pos_ego[1] = self.table_y_min
        if pos_ego[1] > self.table_y_max:
            pos_ego[1] = self.table_y_max
            
        if pos_alt[0] < self.table_x_min:
            pos_alt[0] = self.table_x_min
        if pos_alt[0] > self.table_x_max:
            pos_alt[0] = self.table_x_max
        if pos_alt[1] < self.table_y_min:
            pos_alt[1] = self.table_y_min
        if pos_alt[1] > self.table_y_max:
            pos_alt[1] = self.table_y_max
        
        # keep velocity at a maximum value
        if vel_mag_ego > self.max_paddle_vel:
            vel_ego = [vel_ego[0] / vel_mag_ego * self.max_paddle_vel, vel_ego[1] / vel_mag_ego * self.max_paddle_vel]
            self.paddles['paddle_ego'][0].linearVelocity = b2Vec2(vel_ego[0], vel_ego[1])
        if vel_mag_alt > self.max_paddle_vel:
            vel_alt = [vel_alt[0] / vel_mag_alt * self.max_paddle_vel, vel_alt[1] / vel_mag_alt * self.max_paddle_vel]
            self.paddles['paddle_alt'][0].linearVelocity = b2Vec2(vel_alt[0], vel_alt[1])
        
        self.world.Step(self.time_per_step, 10, 10)
        
        # why do we do this? Because in the real world we have downward force and it is unlikely a paddle will change pos/vel 
        # because of hitting a puck
        self.paddles['paddle_ego'][0].linearVelocity = b2Vec2(vel_ego[0], vel_ego[1])
        self.paddles['paddle_alt'][0].linearVelocity = b2Vec2(vel_alt[0], vel_alt[1])
        self.paddles['paddle_ego'][0].position = (new_pos_ego[0], new_pos_ego[1])
        self.paddles['paddle_alt'][0].position = (new_pos_alt[0], new_pos_alt[1])

        # todo: figure out how to determine if puck was hit by object.
        # contacts, contact_names = self.get_contacts()
        # hit_a_puck = self.respond_contacts(contact_names)
        # # hacky way of determing if puck was hit below TODO: fix later!
        # hit_a_puck = np.any(contacts) # check if any are true
        
        # let's fix. if paddle hits a puck, then let's not change it's position
        
        
        state_info = self.get_current_state()
        return state_info

    def get_contacts(self):
        contacts = list()
        shape_pointers = ([self.paddles[bn][0] for bn in self.paddle_names]  + \
                         [self.pucks[bn][0] for bn in self.puck_names] + [self.blocks[pn][0] for pn in self.block_names] + \
                         [self.obstacles[pn][0] for pn in self.obstacle_names] + [self.targets[pn][0] for pn in self.target_names])
        names = self.paddle_names + self.puck_names + self.block_names + self.obstacle_names + self.target_names
        contact_names = {n: list() for n in names}
        for bn in names:
            all_contacts = np.zeros(len(shape_pointers)).astype(bool)
            for contact in self.object_dict[bn].contacts:
                if contact.contact.touching:
                    contact_bool = np.array([(contact.other == bp and contact.contact.touching) for bp in shape_pointers])
                    contact_names[bn] += [sn for sn, bp in zip(names, shape_pointers) if (contact.other == bp)]
                else:
                    contact_bool = np.zeros(len(shape_pointers)).astype(bool)
                all_contacts += contact_bool
            contacts.append(all_contacts)
        return np.stack(contacts, axis=0), contact_names

    def respond_contacts(self, contact_names):
        hit_a_puck = list()
        for tn in self.target_names:
            for cn in contact_names[tn]: 
                if cn.find("puck") != -1:
                    hit_a_puck.append(cn)
        if self.absorb_target:
            for cn in hit_a_puck:
                self.world.DestroyBody(self.object_dict[cn])
                del self.object_dict[cn]
        return hit_a_puck # TODO: record a destroyed flag
